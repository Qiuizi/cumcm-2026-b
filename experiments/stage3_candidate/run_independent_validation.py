"""
run_independent_validation.py —— 验证 2：六个全新场景 × A/C 配对（12 局，跑完即停）

预注册（在运行前固定；不在运行中调参、不换种子）
--------------------------------------------------
  10 源: seed 9501, 9502
  13 源: seed 9513, 9514
  16 源: seed 9521, 9522
  （以上 seed 在本项目此前任何一轮中都未使用过）
  环境：SimEnvironment.generate_random_case(num_sources=n, is_p4=True, seed=s)，
        dir_ratio=0.5，误差规则由 sim_env._get_noise 以 (位置, 频道) 哈希确定
  内部采样：predictor 的先验抽样为 default_rng(20260912 + 131*channel)，固定可复现
  两臂同场景配对：A = stable（冻结基线），C = history_candidate（历史接收模型候选版）
  共 6 × 2 = 12 局

复用已有校验
--------------------------------------------------
  计费闭合 T = L/5 + 5M + S + 3F + 5N（阈值 1e-3 s）、
  完整清除验收（completed + 未决 0 + 失败 0 + cleared == n_src）、
  逐频道结束证据 —— 口径与阶段2 完全一致（见 stage2 run_paired.py）。

停止条件
--------------------------------------------------
  任一一局未完整完成 ⇒ 立即停止，保留现场，且**不把不完整运行计入省时统计**。
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from launch import HISTORY, STABLE, run_case  # noqa: E402

PREREGISTERED_CASES = [(9501, 10), (9502, 10),
                       (9513, 13), (9514, 13),
                       (9521, 16), (9522, 16)]
ARMS = (STABLE, HISTORY)

CSV_FIELDS = [
    "case", "version", "seed", "n_src",
    "T_virtual_s", "L_dist_m", "M_measures", "S_switches", "F_clear_fail",
    "N_clear_succ", "closure_s", "closure_residual_s", "closure_ok",
    "completion_status", "completed_successfully", "cleared", "absent",
    "unsolved", "failed", "terminal_reason", "real_time_s",
    "no_signal_total", "no_signal_followup", "no_signal_grid_exists",
    "no_signal_grid_not_shrunk", "no_signal_grid_shrunk",
    "model_decisions_used", "model_decision_fallbacks", "model_call_fallbacks",
    "model_score_count", "fallback_reason_hist",
    "action_changed_count", "position_changed_count",
]


def write_run_csv(records, path):
    """把逐局记录写成 CSV（与主流程同一格式；也可用于从 JSON 重建）"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v)
                        for k, v in r.items()})


def rebuild_from_json(json_path, csv_path):
    """从 validation_12runs.json 重建逐局 CSV（报告层重建，不改动运行数据）"""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    recs = data["records"]
    for r in recs:
        c = r.get("no_signal_census") or {}
        for k in ("no_signal_total", "no_signal_followup", "no_signal_grid_exists",
                  "no_signal_grid_not_shrunk", "no_signal_grid_shrunk"):
            r.setdefault(k, c.get(k.replace("no_signal_", ""), ""))
        for k in ("model_decisions_used", "model_decision_fallbacks",
                  "model_call_fallbacks", "model_score_count", "fallback_reason_hist",
                  "action_changed_count", "position_changed_count"):
            r.setdefault(k, "")
    write_run_csv(recs, csv_path)
    print(f"已从 {json_path} 重建逐局 CSV -> {csv_path}  （{len(recs)} 行）")


def main():
    records = []
    incomplete = []

    print("=" * 108)
    print("验证 2：六个全新场景 × A/C 配对（12 局）")
    print("=" * 108)
    print(f"{'案例':<20} {'臂':<18} {'T(s)':>9} {'L(m)':>9} {'M':>4} {'S':>4} {'F':>4} "
          f"{'N':>3} {'闭合残差':>9} {'清除':>7} {'空频道':>6} {'未决':>4} {'失败':>4} "
          f"{'现实(s)':>8}")

    for seed, n_src in PREREGISTERED_CASES:
        for arm in ARMS:
            rec = run_case(arm, seed, n_src)
            rec["case"] = f"P4-{n_src}src-seed{seed}"
            c = rec["no_signal_census"]
            rec.update({
                "no_signal_total": c["no_signal_total"],
                "no_signal_followup": c["no_signal_followup"],
                "no_signal_grid_exists": c["no_signal_grid_exists"],
                "no_signal_grid_not_shrunk": c["no_signal_grid_not_shrunk"],
                "no_signal_grid_shrunk": c["no_signal_grid_shrunk"],
            })
            rec.setdefault("model_decisions_used", "")
            rec.setdefault("model_decision_fallbacks", "")
            rec.setdefault("model_call_fallbacks", "")
            rec.setdefault("model_score_count", "")
            rec.setdefault("fallback_reason_hist", "")
            rec.setdefault("action_changed_count", "")
            rec.setdefault("position_changed_count", "")
            records.append(rec)

            ok = (rec["completed_successfully"] and rec["unsolved"] == 0
                  and rec["failed"] == 0 and rec["cleared"] == n_src
                  and rec["closure_ok"])
            if not ok:
                incomplete.append(rec)

            print(f"{rec['case']:<20} {rec['version']:<18} {rec['T_virtual_s']:>9.2f} "
                  f"{rec['L_dist_m']:>9.1f} {rec['M_measures']:>4} {rec['S_switches']:>4} "
                  f"{rec['F_clear_fail']:>4} {rec['N_clear_succ']:>3} "
                  f"{rec['closure_residual_s']:>9.6f} "
                  f"{rec['cleared']:>3}/{n_src:<3} {rec['absent']:>6} {rec['unsolved']:>4} "
                  f"{rec['failed']:>4} {rec['real_time_s']:>8.2f}"
                  f"{'   <-- 未通过验收' if not ok else ''}")

    # ---------------- 逐局 CSV（先落盘，保留现场） ----------------
    csv_path = os.path.join(OUT_DIR, "validation_12runs.csv")
    write_run_csv(records, csv_path)

    print("\n" + "=" * 108)
    print("验收 1：完整清除与计费闭合")
    print("=" * 108)
    for r in records:
        ok = (r["completed_successfully"] and r["unsolved"] == 0 and r["failed"] == 0
              and r["cleared"] == r["n_src"] and r["closure_ok"])
        print(f"  {r['case']:<20} {r['version']:<18} 完成={r['completed_successfully']} "
              f"清除={r['cleared']}/{r['n_src']} 未决={r['unsolved']} 失败={r['failed']} "
              f"闭合={r['closure_ok']} -> {'PASS' if ok else 'FAIL'}")
    print(f"  全部通过 = {len(incomplete) == 0}")

    if incomplete:
        print("\n！存在未完整完成的局，按要求：停止统计，保留现场。")
        print("  未完成清单：")
        for r in incomplete:
            print(f"    {r['case']} {r['version']} status={r['completion_status']} "
                  f"未决={r['unsolved']} 失败={r['failed']} 原因={r['terminal_reason']}")
        with open(os.path.join(OUT_DIR, "validation_12runs.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"preregistered": PREREGISTERED_CASES, "records": records,
                       "incomplete": incomplete, "aborted": True},
                      f, ensure_ascii=False, indent=2, default=str)
        print(f"\n逐局 CSV（含未完成局）-> {csv_path}")
        return

    # ---------------- 比较 ----------------
    def pair(seed, n_src):
        a = next(r for r in records if r["seed"] == seed and r["version"] == STABLE)
        cc = next(r for r in records if r["seed"] == seed and r["version"] == HISTORY)
        return a, cc

    per_case = []
    for seed, n_src in PREREGISTERED_CASES:
        a, cc = pair(seed, n_src)
        per_case.append({
            "case": a["case"], "seed": seed, "n_src": n_src,
            "A_T": a["T_virtual_s"], "C_T": cc["T_virtual_s"],
            "delta_T": round(cc["T_virtual_s"] - a["T_virtual_s"], 3),
            "A_L": a["L_dist_m"], "C_L": cc["L_dist_m"],
            "A_M": a["M_measures"], "C_M": cc["M_measures"],
            "A_F": a["F_clear_fail"], "C_F": cc["F_clear_fail"],
            "A_no_signal_total": a["no_signal_total"],
            "C_no_signal_total": cc["no_signal_total"],
            "reduction_total": a["no_signal_total"] - cc["no_signal_total"],
            "A_no_signal_followup": a["no_signal_followup"],
            "C_no_signal_followup": cc["no_signal_followup"],
            "reduction_followup": a["no_signal_followup"] - cc["no_signal_followup"],
            "A_grid_not_shrunk": a["no_signal_grid_not_shrunk"],
            "C_grid_not_shrunk": cc["no_signal_grid_not_shrunk"],
            "C_model_decisions_used": cc["model_decisions_used"],
            "C_model_decision_fallbacks": cc["model_decision_fallbacks"],
            "C_model_call_fallbacks": cc["model_call_fallbacks"],
            "C_action_changed": cc["action_changed_count"],
            "C_position_changed": cc["position_changed_count"],
            "C_real_time_s": cc["real_time_s"],
            "A_real_time_s": a["real_time_s"],
        })

    d = [x["delta_T"] for x in per_case]
    stats = {
        "n_cases": len(d),
        "mean_delta": round(statistics.mean(d), 3),
        "median_delta": round(statistics.median(d), 3),
        "worst_regression": round(max(d), 3),
        "best_gain": round(min(d), 3),
        "win": sum(1 for x in d if x < -1e-9),
        "tie": sum(1 for x in d if abs(x) <= 1e-9),
        "loss": sum(1 for x in d if x > 1e-9),
        "mean_saving": round(-statistics.mean(d), 3),
        "median_saving": round(-statistics.median(d), 3),
        "max_regression_s": round(max(d), 3),
    }

    print("\n" + "=" * 108)
    print("验收 2：总虚拟时间比较（ΔT = C − A；负值 = 候选更快）")
    print("=" * 108)
    for x in per_case:
        print(f"  {x['case']:<20} A={x['A_T']:>9.2f}  C={x['C_T']:>9.2f}  "
              f"ΔT={x['delta_T']:>+9.2f}   "
              f"no_signal {x['A_no_signal_total']}->{x['C_no_signal_total']} "
              f"(补测 {x['A_no_signal_followup']}->{x['C_no_signal_followup']})")
    print(f"\n  平均节省 = {stats['mean_saving']:+.3f} s   中位节省 = {stats['median_saving']:+.3f} s")
    print(f"  最大退步 = {stats['max_regression_s']:+.3f} s   最大节省 = {stats['best_gain']:+.3f} s")
    print(f"  胜/平/负 = {stats['win']}/{stats['tie']}/{stats['loss']}")

    # 回退情况
    tot_used = sum(x["C_model_decisions_used"] for x in per_case)
    tot_dec_fb = sum(x["C_model_decision_fallbacks"] for x in per_case)
    tot_call_fb = sum(x["C_model_call_fallbacks"] for x in per_case)
    print(f"\n  回退：用上模型的决策 {tot_used}，整体回退决策 {tot_dec_fb}，"
          f"逐调用回退 {tot_call_fb}")
    print(f"  实际改变动作合计 {sum(x['C_action_changed'] for x in per_case)}，"
          f"改变补测点合计 {sum(x['C_position_changed'] for x in per_case)}")

    # 最大退步案例的主要成本来源
    worst = max(per_case, key=lambda x: x["delta_T"])
    if worst["delta_T"] > 0:
        A = next(r for r in records
                 if r["seed"] == worst["seed"] and r["version"] == STABLE)
        C = next(r for r in records
                 if r["seed"] == worst["seed"] and r["version"] == HISTORY)
        contrib = {
            "distance_cost_delta_s": round((C["L_dist_m"] - A["L_dist_m"]) / 5.0, 2),
            "measure_cost_delta_s": (C["M_measures"] - A["M_measures"]) * 5,
            "switch_cost_delta_s": C["S_switches"] - A["S_switches"],
            "clear_fail_cost_delta_s": (C["F_clear_fail"] - A["F_clear_fail"]) * 3,
        }
        contrib["sum_s"] = round(sum(contrib.values()), 2)
    else:
        contrib = None

    summary = {
        "preregistered": PREREGISTERED_CASES, "arms": list(ARMS),
        "all_complete": True, "stats": stats, "per_case": per_case,
        "model_usage": {"decisions_with_model": tot_used,
                        "decision_fallbacks": tot_dec_fb,
                        "call_fallbacks": tot_call_fb},
        "worst_case": worst if worst["delta_T"] > 0 else None,
        "worst_case_cost_attribution": contrib,
    }

    print("\n" + "=" * 108)
    if worst["delta_T"] > 0:
        print(f"最大退步案例 {worst['case']} 的 ΔT = {worst['delta_T']:+.2f} s，成本分解：")
        for k, v in contrib.items():
            print(f"    {k:<28} = {v:+.2f}")
    else:
        print("本轮没有退步案例（所有配对 ΔT ≤ 0）。")

    # ---------------- 汇总 CSV ----------------
    sum_path = os.path.join(OUT_DIR, "validation_summary.csv")
    with open(sum_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(per_case[0].keys()))
        w.writeheader()
        w.writerows(per_case)

    stat_path = os.path.join(OUT_DIR, "validation_stats.csv")
    with open(stat_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["项", "值"])
        for k, v in stats.items():
            w.writerow([k, v])
        w.writerow(["model_decisions_used", tot_used])
        w.writerow(["model_decision_fallbacks", tot_dec_fb])
        w.writerow(["model_call_fallbacks", tot_call_fb])
        w.writerow(["C_action_changed_total", sum(x["C_action_changed"] for x in per_case)])
        w.writerow(["C_position_changed_total", sum(x["C_position_changed"] for x in per_case)])

    with open(os.path.join(OUT_DIR, "validation_12runs.json"), "w",
              encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f,
                  ensure_ascii=False, indent=2, default=str)

    print(f"\n逐局 CSV   -> {csv_path}")
    print(f"汇总 CSV   -> {sum_path}")
    print(f"统计 CSV   -> {stat_path}")
    print(f"完整记录   -> {os.path.join(OUT_DIR, 'validation_12runs.json')}")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--rebuild-csv":
        rebuild_from_json(sys.argv[2],
                          os.path.join(OUT_DIR, "validation_12runs.csv"))
    else:
        main()
