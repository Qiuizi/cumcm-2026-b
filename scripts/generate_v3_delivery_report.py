"""
generate_v3_delivery_report.py - V3 候选版交付核验与多版本逐案例严格配对核算
核验规范：
1. 覆盖 6 组固定案例 (seed 110, 113, 116, benchmark 4000, 4300, 4600)
2. 同案例配对对比三版本：
   - V1 (基线冻结版): v3.3-scan-off-frozen (本地完全冻结副本)
   - V2 (仅修评分版): v3.3.1-scorefix-only (修复预测法向与闭环网格评分，未开启首任务2-opt)
   - V3 (候选交付版): v3.4-scorefix-2opthead (修复评分 + 开启开放路线首任务2-opt)
3. 统计口径：
   - 明确分别输出 mean(T/N) (逐案例算术均值) 与 sum(T)/sum(N) (总体加权平均值)
   - 统计异常计数：empty_prediction_count (预测空集) 与 plan_uncovered_count (覆盖计划未命中样本)
   - 统计调度：dispatched_head_change_count (2-opt前首任务与最终实际派发首任务不同次数) 与 total_2opt_swaps (内部交换总次数)
   - 现实耗时：每局现实运行总时间 real_time_s 与最大单次决策耗时 max_single_decision_ms，核查 1200s 现实时钟退出余量
4. 导出交付核验 CSV 至 results/v3_delivery_verification.csv
"""

import sys
import os
import csv
import time
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine as StrategyEngineNew
from strategy_engine_frozen import StrategyEngine as StrategyEngineFrozen


def run_delivery_verification():
    cases = [
        {"case_id": "seed-110", "sources": 10, "seed": 110},
        {"case_id": "seed-113", "sources": 13, "seed": 113},
        {"case_id": "seed-116", "sources": 16, "seed": 116},
        {"case_id": "bench-4000", "sources": 10, "seed": 4000},
        {"case_id": "bench-4300", "sources": 13, "seed": 4300},
        {"case_id": "bench-4600", "sources": 16, "seed": 4600},
    ]

    records = []

    print("=" * 95)
    print("【V3 候选版交付核验】6 组固定案例全景逐案例配对测试")
    print("=" * 95)

    for c_info in cases:
        cid = c_info["case_id"]
        n_src = c_info["sources"]
        seed = c_info["seed"]
        print(f"\n>>> 正在评测案例: {cid} (源数={n_src}, 随机种子={seed}) <<<")

        # 1. 运行 V1 (基线冻结版)
        env_v1 = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        d_v1 = LocalSimDriver(env_v1)
        eng_v1 = StrategyEngineFrozen(driver=d_v1, is_p4=False, version="C", scan_at_clearance=False, verbose=False)
        t0 = time.perf_counter()
        res_v1 = eng_v1.execute()
        real_time_v1 = time.perf_counter() - t0

        # 2. 运行 V2 (仅修评分版: enable_2opt_head=False)
        env_v2 = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        d_v2 = LocalSimDriver(env_v2)
        eng_v2 = StrategyEngineNew(driver=d_v2, is_p4=False, version="C", scan_at_clearance=False, enable_2opt_head=False, verbose=False)
        t0 = time.perf_counter()
        res_v2 = eng_v2.execute()
        real_time_v2 = time.perf_counter() - t0

        # 3. 运行 V3 (候选版: enable_2opt_head=True)
        env_v3 = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        d_v3 = LocalSimDriver(env_v3)
        eng_v3 = StrategyEngineNew(driver=d_v3, is_p4=False, version="C", scan_at_clearance=False, enable_2opt_head=True, verbose=False)
        t0 = time.perf_counter()
        res_v3 = eng_v3.execute()
        real_time_v3 = time.perf_counter() - t0

        row_v1 = {
            "version": "V1 (Frozen Baseline)",
            "version_tag": "v3.3-scan-off-frozen",
            "case_id": cid,
            "sources": n_src,
            "cleared": res_v1["cleared_count"],
            "virtual_time_s": res_v1["virtual_time_s"],
            "unit_time_s": res_v1["virtual_time_s"] / res_v1["cleared_count"],
            "move_dist_m": env_v1.total_distance_m,
            "measure_count": env_v1.measure_count,
            "switch_count": env_v1.switch_count,
            "clear_succ_count": env_v1.clear_succ_count,
            "clear_fail_count": env_v1.clear_fail_count,
            "dispatched_head_change_count": 0,
            "total_2opt_swaps": 0,
            "empty_prediction_count": 0,
            "plan_uncovered_count": 0,
            "real_time_s": real_time_v1,
            "max_single_decision_ms": 0.0,
        }

        row_v2 = {
            "version": "V2 (ScoreFix Only)",
            "version_tag": "v3.3.1-scorefix-only",
            "case_id": cid,
            "sources": n_src,
            "cleared": res_v2["cleared_count"],
            "virtual_time_s": res_v2["virtual_time_s"],
            "unit_time_s": res_v2["virtual_time_s"] / res_v2["cleared_count"],
            "move_dist_m": env_v2.total_distance_m,
            "measure_count": env_v2.measure_count,
            "switch_count": env_v2.switch_count,
            "clear_succ_count": env_v2.clear_succ_count,
            "clear_fail_count": env_v2.clear_fail_count,
            "dispatched_head_change_count": res_v2.get("dispatched_head_change_count", 0),
            "total_2opt_swaps": res_v2.get("total_2opt_swaps", 0),
            "empty_prediction_count": res_v2.get("empty_prediction_count", 0),
            "plan_uncovered_count": res_v2.get("plan_uncovered_count", 0),
            "real_time_s": real_time_v2,
            "max_single_decision_ms": res_v2.get("max_single_decision_ms", 0.0),
        }

        row_v3 = {
            "version": "V3 (Candidate)",
            "version_tag": "v3.4-scorefix-2opthead",
            "case_id": cid,
            "sources": n_src,
            "cleared": res_v3["cleared_count"],
            "virtual_time_s": res_v3["virtual_time_s"],
            "unit_time_s": res_v3["virtual_time_s"] / res_v3["cleared_count"],
            "move_dist_m": env_v3.total_distance_m,
            "measure_count": env_v3.measure_count,
            "switch_count": env_v3.switch_count,
            "clear_succ_count": env_v3.clear_succ_count,
            "clear_fail_count": env_v3.clear_fail_count,
            "dispatched_head_change_count": res_v3.get("dispatched_head_change_count", 0),
            "total_2opt_swaps": res_v3.get("total_2opt_swaps", 0),
            "empty_prediction_count": res_v3.get("empty_prediction_count", 0),
            "plan_uncovered_count": res_v3.get("plan_uncovered_count", 0),
            "real_time_s": real_time_v3,
            "max_single_decision_ms": res_v3.get("max_single_decision_ms", 0.0),
        }

        records.extend([row_v1, row_v2, row_v3])

        print(f"  V1 (冻结基线): T={row_v1['virtual_time_s']:7.1f}s, 路程={row_v1['move_dist_m']:6.0f}m, T/N={row_v1['unit_time_s']:5.1f}s, 现实={row_v1['real_time_s']:.2f}s")
        print(f"  V2 (修评分版): T={row_v2['virtual_time_s']:7.1f}s, 路程={row_v2['move_dist_m']:6.0f}m, T/N={row_v2['unit_time_s']:5.1f}s, 现实={row_v2['real_time_s']:.2f}s (空集={row_v2['empty_prediction_count']}, 未覆盖={row_v2['plan_uncovered_count']}, 最大单次决策={row_v2['max_single_decision_ms']:.1f}ms)")
        print(f"  V3 (首任务2-opt): T={row_v3['virtual_time_s']:7.1f}s, 路程={row_v3['move_dist_m']:6.0f}m, T/N={row_v3['unit_time_s']:5.1f}s, 现实={row_v3['real_time_s']:.2f}s (派发首任务变更={row_v3['dispatched_head_change_count']}次, 内部交换={row_v3['total_2opt_swaps']}次, 净省={row_v1['virtual_time_s']-row_v3['virtual_time_s']:+.1f}s)")

    # 导出 CSV
    os.makedirs("results", exist_ok=True)
    csv_path = "results/v3_delivery_verification.csv"
    fieldnames = [
        "Case_ID", "Sources_N", "Version_Tag", "Version_Desc",
        "Cleared_N", "Virtual_Time_T_s", "Unit_Time_T_over_N_s",
        "Total_Move_Dist_m", "Measure_Count", "Channel_Switch_Count",
        "Clear_Succ_Count", "Clear_Fail_Count",
        "Dispatched_Head_Change_Count", "Total_2opt_Swaps",
        "Empty_Prediction_Count", "Plan_Uncovered_Count",
        "Real_Time_s", "Max_Single_Decision_ms"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for r in records:
            writer.writerow([
                r["case_id"], r["sources"], r["version_tag"], r["version"],
                r["cleared"], f"{r['virtual_time_s']:.2f}", f"{r['unit_time_s']:.2f}",
                f"{r['move_dist_m']:.1f}", r["measure_count"], r["switch_count"],
                r["clear_succ_count"], r["clear_fail_count"],
                r["dispatched_head_change_count"], r["total_2opt_swaps"],
                r["empty_prediction_count"], r["plan_uncovered_count"],
                f"{r['real_time_s']:.2f}", f"{r['max_single_decision_ms']:.2f}"
            ])

    print("\n" + "=" * 95)
    print("【逐版本均值核算与统计分析】")
    print("=" * 95)

    for v_desc, v_tag in [("V1 (Frozen Baseline)", "v3.3-scan-off-frozen"),
                          ("V2 (ScoreFix Only)", "v3.3.1-scorefix-only"),
                          ("V3 (Candidate)", "v3.4-scorefix-2opthead")]:
        v_recs = [r for r in records if r["version_tag"] == v_tag]
        sum_T = sum(r["virtual_time_s"] for r in v_recs)
        sum_N = sum(r["cleared"] for r in v_recs)
        mean_unit_T = float(np.mean([r["unit_time_s"] for r in v_recs]))
        weighted_unit_T = sum_T / sum_N
        mean_dist = float(np.mean([r["move_dist_m"] for r in v_recs]))
        tot_empty = sum(r["empty_prediction_count"] for r in v_recs)
        tot_uncov = sum(r["plan_uncovered_count"] for r in v_recs)
        tot_head_chg = sum(r["dispatched_head_change_count"] for r in v_recs)
        tot_swaps = sum(r["total_2opt_swaps"] for r in v_recs)
        max_real = max(r["real_time_s"] for r in v_recs)
        mean_real = float(np.mean([r["real_time_s"] for r in v_recs]))
        max_dec_ms = max(r["max_single_decision_ms"] for r in v_recs)

        print(f"\n--- {v_desc} [{v_tag}] ---")
        print(f"  • 案例总清除数 sum(N):          {sum_N} / 78")
        print(f"  • 虚拟总耗时 sum(T):            {sum_T:.2f} s")
        print(f"  • 口径 A: 逐案例算术平均 mean(T/N): {mean_unit_T:.2f} s/目标")
        print(f"  • 口径 B: 总体加权平均 sum(T)/sum(N): {weighted_unit_T:.2f} s/目标")
        print(f"  • 平均移动距离:                 {mean_dist:.1f} m")
        print(f"  • 派发首任务变更轮数:           {tot_head_chg} 轮")
        print(f"  • 2-opt 内部交换总次数:         {tot_swaps} 次")
        print(f"  • 预测网格空集触发次数:         {tot_empty} 次 (已按不可行惩罚1e9剔除，无300s假时间)")
        print(f"  • 覆盖计划未命中样本次数:       {tot_uncov} 次 (已按不可行惩罚1e9剔除)")
        print(f"  • 现实运行时钟:                 单局最大 {max_real:.2f}s, 均值 {mean_real:.2f}s (时钟限制 1200s, 剩余退出余量 {1200 - max_real:.2f}s)")
        print(f"  • 最大单次决策耗时:             {max_dec_ms:.2f} ms")

    print(f"\n>>> 交付 CSV 报告已成功输出至: {csv_path} <<<")

if __name__ == "__main__":
    run_delivery_verification()
