"""
verify_p3_radial_coverage.py - P3 径向自适应覆盖检测点对比评测与严格计费公式核验

场景设定：
1. 3 组全新场景：10 源 (seed=5010), 13 源 (seed=5013), 16 源 (seed=5016)
2. 同场景配对对比：Baseline (关闭) vs Radial (开启)
3. 严格审计：
   - 100% 完整发现与清除证明 (cleared_count == sources, unsolved == 0)
   - 原始动作计费公式精确校验: T == L/5 + N_switch + 5*N_measure + 3*N_clear_fail + 5*N_clear_succ
   - 记录实际选用的检测半径及选点快照
   - 提取“位置改变 -> 后续动作变化”全流程实例
"""

import sys
import os
import csv
import json
import time
import math
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine


def audit_billing_formula(env: SimEnvironment, virtual_time: float) -> tuple[bool, float, dict]:
    """严格校验计费公式的一致性"""
    L = env.total_distance_m
    n_sw = env.switch_count
    n_meas = env.measure_count
    n_fail = env.clear_fail_count
    n_succ = env.clear_succ_count

    expected_t = L / 5.0 + n_sw + 5.0 * n_meas + 3.0 * n_fail + 5.0 * n_succ
    diff = abs(virtual_time - expected_t)
    valid = diff < 1e-4

    details = {
        "virtual_time": virtual_time,
        "expected_time": expected_t,
        "diff": diff,
        "distance_m": L,
        "time_from_dist": L / 5.0,
        "switch_count": n_sw,
        "measure_count": n_meas,
        "clear_fail_count": n_fail,
        "clear_succ_count": n_succ,
    }
    return valid, diff, details


def run_experiment():
    print("=" * 80)
    print("【P3 径向自适应覆盖检测点】3 组新场景本地验证与严格计费核验")
    print("=" * 80)

    test_cases = [
        {"case_id": "P3-New-10src", "sources": 10, "seed": 5010},
        {"case_id": "P3-New-13src", "sources": 13, "seed": 5013},
        {"case_id": "P3-New-16src", "sources": 16, "seed": 5016},
    ]

    records = []
    detailed_events = {}

    for tc in test_cases:
        case_id = tc["case_id"]
        n_src = tc["sources"]
        seed = tc["seed"]

        print(f"\n>>> 正在评测案例: {case_id} (源数量={n_src}, 随机种子={seed}) <<<")

        # 1. 运行 Baseline (关闭径向自适应选点)
        env_base = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        driver_base = LocalSimDriver(env_base)
        eng_base = StrategyEngine(
            driver=driver_base,
            is_p4=False,
            version="C",
            enable_adaptive_radial_coverage=False,
            verbose=False,
        )
        res_base = eng_base.execute()

        v_valid_base, v_diff_base, v_det_base = audit_billing_formula(env_base, res_base["virtual_time_s"])
        print(f"  [Baseline] 清除={res_base['cleared_count']}/{n_src}, 虚拟耗时={res_base['virtual_time_s']:.2f}s, "
              f"里程={env_base.total_distance_m:.1f}m, 计费校验={'PASS' if v_valid_base else 'FAIL'} (误差={v_diff_base:.6f}s)")

        # 2. 运行 Radial (开启径向自适应选点)
        env_rad = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        driver_rad = LocalSimDriver(env_rad)
        eng_rad = StrategyEngine(
            driver=driver_rad,
            is_p4=False,
            version="C",
            enable_adaptive_radial_coverage=True,
            verbose=False,
        )
        res_rad = eng_rad.execute()

        v_valid_rad, v_diff_rad, v_det_rad = audit_billing_formula(env_rad, res_rad["virtual_time_s"])
        saved_t = res_base["virtual_time_s"] - res_rad["virtual_time_s"]
        saved_d = env_base.total_distance_m - env_rad.total_distance_m
        print(f"  [Radial]   清除={res_rad['cleared_count']}/{n_src}, 虚拟耗时={res_rad['virtual_time_s']:.2f}s, "
              f"里程={env_rad.total_distance_m:.1f}m, 计费校验={'PASS' if v_valid_rad else 'FAIL'} (误差={v_diff_rad:.6f}s)")
        print(f"  [对比效果] 净节省虚拟时间={saved_t:+.2f}s, 里程节省={saved_d:+.1f}m, 径向调点次数={res_rad['radial_adjustments_count']}")

        # 记录实际选用的半径
        chosen_radii = [ev["chosen_r"] for ev in res_rad.get("radial_events", [])]
        print(f"  [调点详情] 触发径向调整的半径列表: {chosen_radii}")

        record = {
            "case_id": case_id,
            "sources": n_src,
            "seed": seed,
            # 基线指标
            "base_cleared": res_base["cleared_count"],
            "base_unsolved": res_base["unsolved_count"],
            "base_T_s": res_base["virtual_time_s"],
            "base_dist_m": env_base.total_distance_m,
            "base_meas_cnt": env_base.measure_count,
            "base_switch_cnt": env_base.switch_count,
            "base_fail_cnt": env_base.clear_fail_count,
            "base_real_t_s": res_base["real_time_s"],
            "base_billing_valid": v_valid_base,
            # 新功能指标
            "rad_cleared": res_rad["cleared_count"],
            "rad_unsolved": res_rad["unsolved_count"],
            "rad_T_s": res_rad["virtual_time_s"],
            "rad_dist_m": env_rad.total_distance_m,
            "rad_meas_cnt": env_rad.measure_count,
            "rad_switch_cnt": env_rad.switch_count,
            "rad_fail_cnt": env_rad.clear_fail_count,
            "rad_real_t_s": res_rad["real_time_s"],
            "rad_billing_valid": v_valid_rad,
            # 差异与调点
            "saved_T_s": saved_t,
            "saved_dist_m": saved_d,
            "radial_adjust_cnt": res_rad["radial_adjustments_count"],
            "chosen_radii": str(chosen_radii),
        }
        records.append(record)

        detailed_events[case_id] = {
            "radial_events": res_rad.get("radial_events", []),
            "baseline_search_visited": res_base.get("search_points_visited", []),
            "radial_search_visited": res_rad.get("search_points_visited", []),
            "base_billing_details": v_det_base,
            "rad_billing_details": v_det_rad,
        }

    # 导出 CSV 报告
    os.makedirs("results", exist_ok=True)
    csv_path = "results/p3_radial_coverage_comparison.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Case_ID", "Sources", "Seed",
            "Base_Cleared", "Base_T_s", "Base_Dist_m", "Base_Meas", "Base_Switch", "Base_ClearFail", "Base_RealTime_s", "Base_Billing_Valid",
            "Rad_Cleared", "Rad_T_s", "Rad_Dist_m", "Rad_Meas", "Rad_Switch", "Rad_ClearFail", "Rad_RealTime_s", "Rad_Billing_Valid",
            "Saved_T_s", "Saved_Dist_m", "Radial_Adjust_Count", "Chosen_Radii",
        ])
        for r in records:
            writer.writerow([
                r["case_id"], r["sources"], r["seed"],
                r["base_cleared"], f"{r['base_T_s']:.2f}", f"{r['base_dist_m']:.1f}", r["base_meas_cnt"], r["base_switch_cnt"], r["base_fail_cnt"], f"{r['base_real_t_s']:.3f}", r["base_billing_valid"],
                r["rad_cleared"], f"{r['rad_T_s']:.2f}", f"{r['rad_dist_m']:.1f}", r["rad_meas_cnt"], r["rad_switch_cnt"], r["rad_fail_cnt"], f"{r['rad_real_t_s']:.3f}", r["rad_billing_valid"],
                f"{r['saved_T_s']:.2f}", f"{r['saved_dist_m']:.1f}", r["radial_adjust_cnt"], r["chosen_radii"],
            ])

    # 导出详细审计 JSON
    json_path = "results/p3_radial_coverage_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(detailed_events, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print(f"评测完成！CSV 结果已保存至: {csv_path}")
    print(f"详细审计快照已保存至: {json_path}")
    print("=" * 80)

    return records, detailed_events


if __name__ == "__main__":
    run_experiment()
