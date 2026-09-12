"""
verify_p3_unchanged_after_p4_fix.py - 证明 P4 基线修复未改变 P3 行为

方法：用与 results/p3_radial_coverage_9cases_summary.csv 完全相同的配置
重新运行既有 P3 场景，并与既有记录逐字段比对（T / L / M / S / F / N / 清除数）。

配置严格取自 scripts/verify_p3_radial_coverage_rigorous.py：
  is_p4=False, version="C", scan_at_clearance=False, enable_2opt_head=True
  fixed_baseline 臂: enable_adaptive_radial_coverage=False
  radial_candidate 臂: enable_adaptive_radial_coverage=True
"""

import sys
import os
import csv
import json

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CSV_PATH = os.path.join(ROOT, "results", "p3_radial_coverage_9cases_summary.csv")
OUT_DIR = os.path.join(ROOT, "results", "p4_fix", "verification")

CASES = [
    {"case_id": "P3-New-10src-6010", "sources": 10, "seed": 6010},
    {"case_id": "P3-Corr-13src-5013", "sources": 13, "seed": 5013},
]


def run(case, radial: bool):
    env = SimEnvironment.generate_random_case(num_sources=case["sources"], is_p4=False, seed=case["seed"])
    drv = LocalSimDriver(env)
    eng = StrategyEngine(driver=drv, is_p4=False, version="C", scan_at_clearance=False,
                         enable_2opt_head=True, enable_adaptive_radial_coverage=radial, verbose=False)
    s = eng.execute()
    return {
        "cleared": s["cleared_count"], "T": s["virtual_time_s"],
        "L": env.total_distance_m, "M": env.measure_count, "S": env.switch_count,
        "F": env.clear_fail_count, "N": env.clear_succ_count,
        "completion_status": s.get("completion_status"), "failed": s.get("failed_count", 0),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CSV_PATH, encoding="utf-8") as f:
        recorded = {r["Case_ID"]: r for r in csv.DictReader(f)}

    print("=" * 108)
    print("【P3 行为不变性回归】P4 修复后重跑既有 P3 场景，与既有记录逐字段比对")
    print("=" * 108)

    results = []
    all_ok = True
    for case in CASES:
        rec = recorded[case["case_id"]]
        for arm, radial, prefix in (("baseline(2opt_head=True, radial=off)", False, "Base"),
                                    ("radial_candidate(2opt_head=True, radial=on)", True, "Rad")):
            r = run(case, radial)
            exp = {
                "cleared": int(rec[f"{prefix}_Cleared"]), "T": float(rec[f"{prefix}_T_s"]),
                "L": float(rec[f"{prefix}_Dist_m"]), "M": int(rec[f"{prefix}_M"]),
                "S": int(rec[f"{prefix}_S"]), "F": int(rec[f"{prefix}_F"]), "N": int(rec[f"{prefix}_N"]),
            }
            checks = {
                "cleared": r["cleared"] == exp["cleared"],
                "M": r["M"] == exp["M"], "S": r["S"] == exp["S"],
                "F": r["F"] == exp["F"], "N": r["N"] == exp["N"],
                "L(1位小数)": round(r["L"], 1) == exp["L"],
                "T(2位小数)": round(r["T"], 2) == exp["T"],
            }
            ok = all(checks.values())
            all_ok = all_ok and ok
            print(f"  {case['case_id']:20s} {arm:42s} -> {'PASS' if ok else 'FAIL'}")
            print(f"      实测 T={r['T']:.3f} L={r['L']:.3f} M={r['M']} S={r['S']} F={r['F']} N={r['N']} "
                  f"cleared={r['cleared']} status={r['completion_status']}")
            print(f"      记录 T={exp['T']:.2f} L={exp['L']:.1f} M={exp['M']} S={exp['S']} F={exp['F']} N={exp['N']} "
                  f"cleared={exp['cleared']}")
            if not ok:
                for k, v in checks.items():
                    if not v:
                        print(f"      !! 不一致: {k}")
            results.append({"case_id": case["case_id"], "arm": arm, "measured": r,
                            "expected": exp, "checks": checks, "pass": ok})

    print("-" * 108)
    print(f"总体判定: {'PASS —— P3 行为与合入后记录逐字段一致，未受 P4 修复影响' if all_ok else 'FAIL'}")
    print("=" * 108)
    with open(os.path.join(OUT_DIR, "p3_unchanged_after_p4_fix.json"), "w", encoding="utf-8") as f:
        json.dump({"records": results, "overall_pass": bool(all_ok)}, f, indent=2, ensure_ascii=False)
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
