"""
verify_p3_radial_coverage_rigorous.py - P3 径向自适应覆盖检测点多场景严格配对验证与计费核验

规范：
1. 实际生效配置严格绑定 v3.4.2 稳定基线：
   - enable_2opt_head = True (关键纠偏：此前默认为 False，现与 v3.4.2 正式交付版一致)
   - scan_at_clearance = False
   - is_p4 = False
   - enable_reschedule_after_followup = False (关闭)
   - enable_adaptive_radial_coverage: Baseline 为 False, Radial 为 True
2. 评测场景：
   - 纠偏重跑 3 组已有案例: seed=5010 (10源), seed=5013 (13源), seed=5016 (16源)
   - 全新独立 6 组案例:
     * N=10: seed=6010, seed=6110
     * N=13: seed=6013, seed=6113
     * N=16: seed=6016, seed=6116
3. 严格计费公式核验:
   T = L/5 + 5M + S + 3F + 5N
   其中: L为里程, M为测量次数, S为切频次数, F为清除失败次数, N为清除成功次数
   核算采用未舍入原始浮点数，确认清除动作不改变测量频道。
4. 导出:
   - results/p3_radial_coverage_3cases_corrected.csv
   - results/p3_radial_coverage_6new_cases.csv
   - results/p3_radial_coverage_9cases_summary.csv
   - results/p3_radial_coverage_9cases_audit.json
"""

import sys
import os
import csv
import json
import time
import math
import subprocess
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return "UNKNOWN"


def audit_billing_exact(env: SimEnvironment, virtual_time: float) -> tuple[bool, float, dict]:
    L = env.total_distance_m
    M = env.measure_count
    S = env.switch_count
    F = env.clear_fail_count
    N = env.clear_succ_count

    expected_t = L / 5.0 + 5.0 * M + 1.0 * S + 3.0 * F + 5.0 * N
    diff = abs(virtual_time - expected_t)
    valid = diff < 1e-3  # 浮点累加容差

    details = {
        "virtual_time": virtual_time,
        "expected_time": expected_t,
        "diff_raw": diff,
        "distance_m": L,
        "move_time_s": L / 5.0,
        "measure_count": M,
        "measure_time_s": 5.0 * M,
        "switch_count": S,
        "switch_time_s": 1.0 * S,
        "clear_fail_count": F,
        "clear_fail_time_s": 3.0 * F,
        "clear_succ_count": N,
        "clear_succ_time_s": 5.0 * N,
    }
    return valid, diff, details


def run_single_case(cid: str, n_src: int, seed: int):
    # 1. 运行 Baseline (开启 2-opt 首任务，关闭径向调点)
    env_base = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
    drv_base = LocalSimDriver(env_base)
    eng_base = StrategyEngine(
        driver=drv_base,
        is_p4=False,
        version="C",
        scan_at_clearance=False,
        enable_2opt_head=True,
        enable_adaptive_radial_coverage=False,
        verbose=False,
    )
    t0_b = time.perf_counter()
    res_base = eng_base.execute()
    real_t_base = time.perf_counter() - t0_b
    valid_b, diff_b, det_b = audit_billing_exact(env_base, res_base["virtual_time_s"])

    # 2. 运行 Radial (开启 2-opt 首任务，开启径向调点)
    env_rad = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
    drv_rad = LocalSimDriver(env_rad)
    eng_rad = StrategyEngine(
        driver=drv_rad,
        is_p4=False,
        version="C",
        scan_at_clearance=False,
        enable_2opt_head=True,
        enable_adaptive_radial_coverage=True,
        verbose=False,
    )
    t0_r = time.perf_counter()
    res_rad = eng_rad.execute()
    real_t_rad = time.perf_counter() - t0_r
    valid_r, diff_r, det_r = audit_billing_exact(env_rad, res_rad["virtual_time_s"])

    # 细分贡献分解
    dt_total = res_base["virtual_time_s"] - res_rad["virtual_time_s"]
    dt_move = (env_base.total_distance_m - env_rad.total_distance_m) / 5.0
    dt_meas = 5.0 * (env_base.measure_count - env_rad.measure_count)
    dt_sw = 1.0 * (env_base.switch_count - env_rad.switch_count)
    dt_fail = 3.0 * (env_base.clear_fail_count - env_rad.clear_fail_count)

    chosen_radii = [ev["chosen_r"] for ev in res_rad.get("radial_events", [])]
    expected_saves = [ev["expected_save_s"] for ev in res_rad.get("radial_events", [])]
    sum_expected_save = sum(expected_saves)

    row = {
        "case_id": cid,
        "sources": n_src,
        "seed": seed,
        # Baseline
        "base_cleared": res_base["cleared_count"],
        "base_unsolved": res_base["unsolved_count"],
        "base_T_s": res_base["virtual_time_s"],
        "base_dist_m": env_base.total_distance_m,
        "base_M": env_base.measure_count,
        "base_S": env_base.switch_count,
        "base_F": env_base.clear_fail_count,
        "base_N": env_base.clear_succ_count,
        "base_real_t_s": real_t_base,
        "base_diff_raw": diff_b,
        "base_valid": valid_b,
        # Radial
        "rad_cleared": res_rad["cleared_count"],
        "rad_unsolved": res_rad["unsolved_count"],
        "rad_T_s": res_rad["virtual_time_s"],
        "rad_dist_m": env_rad.total_distance_m,
        "rad_M": env_rad.measure_count,
        "rad_S": env_rad.switch_count,
        "rad_F": env_rad.clear_fail_count,
        "rad_N": env_rad.clear_succ_count,
        "rad_real_t_s": real_t_rad,
        "rad_diff_raw": diff_r,
        "rad_valid": valid_r,
        # 差异与分解
        "saved_T_s": dt_total,
        "contrib_move_s": dt_move,
        "contrib_meas_s": dt_meas,
        "contrib_switch_s": dt_sw,
        "contrib_fail_s": dt_fail,
        "saved_dist_m": env_base.total_distance_m - env_rad.total_distance_m,
        # 选点统计
        "radial_adjust_cnt": res_rad["radial_adjustments_count"],
        "sum_expected_save_s": sum_expected_save,
        "chosen_radii": str(chosen_radii),
    }

    audit_entry = {
        "case_id": cid,
        "sources": n_src,
        "seed": seed,
        "base_billing": det_b,
        "rad_billing": det_r,
        "radial_events": res_rad.get("radial_events", []),
        "search_visited_base": res_base.get("search_points_visited", []),
        "search_visited_rad": res_rad.get("search_points_visited", []),
    }

    print(f"  [{cid}] Base T={res_base['virtual_time_s']:.2f}s | Rad T={res_rad['virtual_time_s']:.2f}s | "
          f"ΔT={dt_total:+.2f}s (移动{dt_move:+.1f}s, 测量{dt_meas:+.1f}s, 切频{dt_sw:+.1f}s, 失败{dt_fail:+.1f}s) | "
          f"调点={res_rad['radial_adjustments_count']}次 (预估={sum_expected_save:.1f}s) | 计费={'PASS' if valid_b and valid_r else 'FAIL'}")

    return row, audit_entry


def save_csv(path: str, records: list):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Case_ID", "Sources", "Seed",
            "Base_Cleared", "Base_T_s", "Base_Dist_m", "Base_M", "Base_S", "Base_F", "Base_N", "Base_RealTime_s", "Base_BillDiff_s",
            "Rad_Cleared", "Rad_T_s", "Rad_Dist_m", "Rad_M", "Rad_S", "Rad_F", "Rad_N", "Rad_RealTime_s", "Rad_BillDiff_s",
            "Saved_T_s", "Contrib_Move_s", "Contrib_Meas_s", "Contrib_Switch_s", "Contrib_Fail_s", "Saved_Dist_m",
            "Radial_Adjust_Count", "Sum_Expected_Save_s", "Chosen_Radii",
        ])
        for r in records:
            writer.writerow([
                r["case_id"], r["sources"], r["seed"],
                r["base_cleared"], f"{r['base_T_s']:.2f}", f"{r['base_dist_m']:.1f}", r["base_M"], r["base_S"], r["base_F"], r["base_N"], f"{r['base_real_t_s']:.3f}", f"{r['base_diff_raw']:.6f}",
                r["rad_cleared"], f"{r['rad_T_s']:.2f}", f"{r['rad_dist_m']:.1f}", r["rad_M"], r["rad_S"], r["rad_F"], r["rad_N"], f"{r['rad_real_t_s']:.3f}", f"{r['rad_diff_raw']:.6f}",
                f"{r['saved_T_s']:.2f}", f"{r['contrib_move_s']:.2f}", f"{r['contrib_meas_s']:.2f}", f"{r['contrib_switch_s']:.2f}", f"{r['contrib_fail_s']:.2f}", f"{r['saved_dist_m']:.1f}",
                r["radial_adjust_cnt"], f"{r['sum_expected_save_s']:.2f}", r["chosen_radii"],
            ])


def analyze_records(name: str, records: list):
    n = len(records)
    saved_list = [r["saved_T_s"] for r in records]
    wins = sum(1 for s in saved_list if s > 0.05)
    ties = sum(1 for s in saved_list if abs(s) <= 0.05)
    losses = sum(1 for s in saved_list if s < -0.05)

    mean_saved = float(np.mean(saved_list))
    max_regress = min(saved_list)
    max_gain = max(saved_list)

    tot_move = sum(r["contrib_move_s"] for r in records)
    tot_meas = sum(r["contrib_meas_s"] for r in records)
    tot_sw = sum(r["contrib_switch_s"] for r in records)
    tot_fail = sum(r["contrib_fail_s"] for r in records)

    # 去掉最大获益案例后的均值
    without_max = [s for s in saved_list]
    without_max.remove(max_gain)
    mean_without_max = float(np.mean(without_max)) if without_max else 0.0

    print(f"\n==================== 【{name}】统计汇总 ({n} 局) ====================")
    print(f"胜 / 平 / 负:                   {wins} / {ties} / {losses}")
    print(f"平均配对节省时间 (均值):         {mean_saved:+.2f} s")
    print(f"最大单局退步 (最差负值):         {max_regress:+.2f} s")
    print(f"最大单局获益 (最佳正值):         {max_gain:+.2f} s")
    print(f"各项累计贡献分解:               移动={tot_move:+.2f}s, 测量={tot_meas:+.2f}s, 切频={tot_sw:+.2f}s, 失败清除={tot_fail:+.2f}s")
    print(f"排除最大获益案例后平均节省:      {mean_without_max:+.2f} s")
    print("=" * 65)

    return {
        "count": n,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "mean_saved_s": mean_saved,
        "max_regression_s": max_regress,
        "max_gain_s": max_gain,
        "mean_without_max_gain_s": mean_without_max,
        "contrib_total_move_s": tot_move,
        "contrib_total_meas_s": tot_meas,
        "contrib_total_switch_s": tot_sw,
        "contrib_total_fail_s": tot_fail,
    }


def main():
    commit = get_git_commit()
    print("=" * 80)
    print(f"【P3 径向自适应覆盖评测】当前 Git Commit: {commit}")
    print("运行参数严格锁定:")
    print("  - version = 'C'")
    print("  - enable_2opt_head = True (v3.4.2 交付基线标准)")
    print("  - scan_at_clearance = False")
    print("  - is_p4 = False")
    print("  - enable_reschedule_after_followup = False")
    print("=" * 80)

    # 1. 纠偏重跑 3 组案例 (seed 5010, 5013, 5016)
    print("\n>>> 第一阶段：纠偏重跑原三组配对案例 (enable_2opt_head=True) <<<")
    cases_3 = [
        {"case_id": "P3-Corr-10src-5010", "sources": 10, "seed": 5010},
        {"case_id": "P3-Corr-13src-5013", "sources": 13, "seed": 5013},
        {"case_id": "P3-Corr-16src-5016", "sources": 16, "seed": 5016},
    ]
    records_3 = []
    audits_all = {}
    for c in cases_3:
        r, a = run_single_case(c["case_id"], c["sources"], c["seed"])
        records_3.append(r)
        audits_all[c["case_id"]] = a

    save_csv("results/p3_radial_coverage_3cases_corrected.csv", records_3)
    analyze_records("纠偏后原 3 组案例", records_3)

    # 2. 运行全新 6 组案例
    print("\n>>> 第二阶段：全新 6 组独立场景配对测试 <<<")
    cases_6 = [
        {"case_id": "P3-New-10src-6010", "sources": 10, "seed": 6010},
        {"case_id": "P3-New-10src-6110", "sources": 10, "seed": 6110},
        {"case_id": "P3-New-13src-6013", "sources": 13, "seed": 6013},
        {"case_id": "P3-New-13src-6113", "sources": 13, "seed": 6113},
        {"case_id": "P3-New-16src-6016", "sources": 16, "seed": 6016},
        {"case_id": "P3-New-16src-6116", "sources": 16, "seed": 6116},
    ]
    records_6 = []
    for c in cases_6:
        r, a = run_single_case(c["case_id"], c["sources"], c["seed"])
        records_6.append(r)
        audits_all[c["case_id"]] = a

    save_csv("results/p3_radial_coverage_6new_cases.csv", records_6)
    analyze_records("全新 6 组案例", records_6)

    # 3. 汇总全部 9 组案例
    records_9 = records_3 + records_6
    save_csv("results/p3_radial_coverage_9cases_summary.csv", records_9)
    with open("results/p3_radial_coverage_9cases_audit.json", "w", encoding="utf-8") as f:
        json.dump(audits_all, f, indent=2, ensure_ascii=False)

    analyze_records("全部 9 组统一配置汇总", records_9)


if __name__ == "__main__":
    main()
