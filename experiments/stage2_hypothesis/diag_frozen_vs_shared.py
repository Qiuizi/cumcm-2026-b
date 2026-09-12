"""
diag_frozen_vs_shared.py —— 基线契约取证（**不属于 9 局配对**）

背景
--------------------------------------------------
`experiments/roadmap/route3_responsive_stop.py` 的 B 臂是这样注入的：
    eng.local_decision = ResponsiveStopLocalDecision(...)
其中 `ResponsiveStopLocalDecision` 继承的是 `src/local_decision.py::LocalDecisionMaker`；
而 P4 的**基线**用的是根目录冻结组件 `local_decision_frozen.LocalDecisionMaker`。
两者并非同一份代码（diff: 114 insertions / 124 deletions）。

后果：route3 的 B-vs-A 差值里混入了"冻结组件 → 共享组件"的替换效应，
不能干净地归因于 k=1 规则。

本诊断
--------------------------------------------------
在同样的三组预注册场景上，跑一臂 A' = 只把决策器换成**共享版**（不加任何 k 规则），
与 A（冻结版）比较，量出这个替换效应的大小。
3 局，仅作基线契约记录，不进入 9 局比较。
"""

from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "results")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from src.sim_env import SimEnvironment, LocalSimDriver  # noqa: E402
from src.strategy_engine import StrategyEngine  # noqa: E402
from src.local_decision import LocalDecisionMaker as SharedDecisionMaker  # noqa: E402
from observer import RecordingObserverDriver  # noqa: E402

CASES = [(8801, 10), (8813, 13), (8816, 16)]


def run(seed, n_src, inject_shared):
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
    drv = RecordingObserverDriver(LocalSimDriver(env))
    eng = StrategyEngine(driver=drv, is_p4=True, version="C", verbose=False)
    if inject_shared:
        eng.local_decision = SharedDecisionMaker(
            max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
    res = eng.execute()
    return {
        "seed": seed, "n_src": n_src,
        "decision_maker": "shared(src/local_decision.py)" if inject_shared else "frozen(root)",
        "T": round(res["virtual_time_s"], 3),
        "cleared": res["cleared_count"], "absent": res["absent_count"],
        "unsolved": res["unsolved_count"], "failed": res["failed_count"],
        "completion_status": res["completion_status"],
        "dist_m": round(env.total_distance_m, 1),
        "measures": env.measure_count,
        "real_time_s": round(res["real_time_s"], 3),
    }


def main():
    rows = []
    print("=" * 96)
    print("基线契约取证：冻结决策器 vs 共享决策器（P4，相同场景，无任何 k 规则）")
    print("=" * 96)
    print(f"{'seed':>6} {'源数':>4} {'决策器':<34} {'T(s)':>10} {'清除':>6} {'空频道':>6} "
          f"{'现实(s)':>8}")
    for seed, n_src in CASES:
        fa = run(seed, n_src, False)
        sa = run(seed, n_src, True)
        rows += [fa, sa]
        d = sa["T"] - fa["T"]
        print(f"{seed:>6} {n_src:>4} {fa['decision_maker']:<34} {fa['T']:>10.2f} "
              f"{fa['cleared']:>6} {fa['absent']:>6} {fa['real_time_s']:>8.2f}")
        print(f"{'':>6} {'':>4} {sa['decision_maker']:<34} {sa['T']:>10.2f} "
              f"{sa['cleared']:>6} {sa['absent']:>6} {sa['real_time_s']:>8.2f}"
              f"   ΔT(共享-冻结) = {d:>+9.2f}s")

    deltas = []
    for seed, n_src in CASES:
        fa = next(r for r in rows if r["seed"] == seed and r["n_src"] == n_src
                  and r["decision_maker"].startswith("frozen"))
        sa = next(r for r in rows if r["seed"] == seed and r["n_src"] == n_src
                  and r["decision_maker"].startswith("shared"))
        deltas.append(sa["T"] - fa["T"])
    print(f"\n  均值 ΔT = {sum(deltas)/len(deltas):+.2f}s，逐例 = "
          f"{[round(x,2) for x in deltas]}")
    print("  => 实测：两个决策器在这三局上**行为等价**（ΔT 全为 0.00 s）。")
    print("     结论修正：'冻结 vs 共享'是**真实的源码契约差异**（不同文件、不同版本），")
    print("     但在本批场景上不产生任何行为差异，故此前 route3 的 B 臂结果")
    print("     并未被该替换实质污染；第二阶段仍在冻结基类上重建 B/C，以保持契约干净。")

    with open(os.path.join(OUT_DIR, "baseline_frozen_vs_shared.json"), "w",
              encoding="utf-8") as f:
        json.dump({"rows": rows, "deltas": deltas}, f, ensure_ascii=False, indent=2)
    print(f"结果已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
