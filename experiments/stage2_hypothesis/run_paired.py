"""
run_paired.py —— 阶段2 四. 有限配对验证（9 局，完成后停止）

预注册（在运行前固定，未参与任何调参）
--------------------------------------------------
场景：P4（is_p4=True），dir_ratio=0.5，本地参考环境 src/sim_env.py
  10 源: seed = 8801
  13 源: seed = 8813
  16 源: seed = 8816
三臂（相同的源场景与测向误差规则）：
  A: 原基线（冻结决策器，不做任何替换）
  B: 已有 k=1 简单止损（K1StopFrozenDecision，以冻结决策器为基类）
  C: 历史观测接收预测（CHypothesisDecision，不叠加 k 规则）
共 3×3 = 9 局。

逐局记录：T / L / M / S / F / N、完成状态、未决与失败频道数、逐频道结束证据、
          无信号补测次数、实际派发动作变化数、模型回退次数、现实运行时间。
先验收完整清除，再比较总虚拟时间。计费闭合核对 T = L/5 + 5M + S + 3F + 5N。
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from src.sim_env import SimEnvironment, LocalSimDriver  # noqa: E402
from src.strategy_engine import StrategyEngine  # noqa: E402
from arm_decision import CHypothesisDecision, K1StopFrozenDecision  # noqa: E402
from observer import RecordingObserverDriver  # noqa: E402

# ---- 预注册场景（固定，不得改动）----
PREREGISTERED_CASES = [(8801, 10), (8813, 13), (8816, 16)]
ARMS = ("A", "B", "C")


def no_signal_stats(obs_drv, eng):
    """统计无信号补测：区分"发现前在搜索点上的阴性"与"发现后的补测阴性" """
    first_seen = {}
    for rec in eng.channels.items():
        pass
    detected_t = {}
    for rec in obs_drv.measures:
        if rec["result"] in ("direction", "near"):
            detected_t.setdefault(rec["channel"], rec["t"])
    total = 0
    followups = 0
    for rec in obs_drv.measures:
        if rec["result"] != "no_signal":
            continue
        total += 1
        dt = detected_t.get(rec["channel"])
        if dt is not None and rec["t"] >= dt:
            followups += 1
    return {"no_signal_measures_total": total, "no_signal_followups": followups}


def run_one(seed, n_src, arm):
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
    obs_drv = RecordingObserverDriver(LocalSimDriver(env))
    eng = StrategyEngine(driver=obs_drv, is_p4=True, version="C", verbose=False)

    dec = None
    if arm == "B":
        dec = K1StopFrozenDecision(k=1, max_followups=12,
                                   max_followup_time_s=600.0, margin_s=5.0)
        eng.local_decision = dec
    elif arm == "C":
        dec = CHypothesisDecision(observer=obs_drv, max_followups=12,
                                  max_followup_time_s=600.0, margin_s=5.0)
        eng.local_decision = dec

    t0 = time.time()
    res = eng.execute()
    real_s = time.time() - t0

    T = env.virtual_time_s
    L = env.total_distance_m
    M = env.measure_count
    S = env.switch_count
    F = env.clear_fail_count
    N = env.clear_succ_count
    closure = L / 5.0 + 5.0 * M + 1.0 * S + 3.0 * F + 5.0 * N

    per_channel = {
        str(ch): {"status": st.status, "absence_proof_type": st.absence_proof_type}
        for ch, st in eng.channels.items()
    }
    ns = no_signal_stats(obs_drv, eng)

    rec = {
        "case": f"P4-{n_src}src-seed{seed}",
        "arm": arm, "seed": seed, "n_src": n_src,
        "T_virtual_s": round(T, 3),
        "L_dist_m": round(L, 2),
        "M_measures": M,
        "S_switches": S,
        "F_clear_fail": F,
        "N_clear_succ": N,
        "closure_s": round(closure, 3),
        "closure_residual_s": round(T - closure, 6),
        "closure_ok": abs(T - closure) < 1e-3,
        "cleared": res["cleared_count"],
        "absent": res["absent_count"],
        "unsolved": res["unsolved_count"],
        "failed": res["failed_count"],
        "completion_status": res["completion_status"],
        "completed_successfully": res["completed_successfully"],
        "terminal_reason": res["terminal_reason"],
        "avg_time_per_target_s": round(res["avg_time_per_target"], 3),
        "real_time_s": round(real_s, 3),
        "no_signal_measures_total": ns["no_signal_measures_total"],
        "no_signal_followups": ns["no_signal_followups"],
        "planned_search_points": len(eng.search_points),
        "visited_search_points": res["search_points_visited_count"],
        "absent_coverage_count": res["absent_coverage_count"],
        "absent_upper_bound_count": res["absent_upper_bound_count"],
        "per_channel_end_evidence": per_channel,
    }

    if dec is not None and hasattr(dec, "audit"):
        a = dec.audit()
        rec["action_changed_count"] = a.get("action_changed_count", 0)
        rec["position_changed_count"] = a.get("position_changed_count", 0)
        rec["decision_records"] = a.get("decision_records", [])
        rec["model_update_records"] = a.get("model_updates", [])
    else:
        rec["action_changed_count"] = 0
        rec["position_changed_count"] = 0
        rec["decision_records"] = []
        rec["model_update_records"] = []

    if arm == "B":
        rec["k_rule_triggered"] = getattr(dec, "forced_clear_count", 0)
        rec["model_decision_fallbacks"] = ""
        rec["model_call_fallbacks"] = ""
    elif arm == "C":
        rec["k_rule_triggered"] = ""
        rec["model_decision_fallbacks"] = dec.decision_fallback_count
        rec["model_call_fallbacks"] = dec.call_fallback_count
        rec["model_decisions_used"] = dec.decision_with_model_count
        rec["fallback_reason_hist"] = json.dumps(dec.fallback_reason_hist,
                                                 ensure_ascii=False)
    else:
        rec["k_rule_triggered"] = ""
        rec["model_decision_fallbacks"] = ""
        rec["model_call_fallbacks"] = ""

    return rec


CSV_FIELDS = [
    "case", "arm", "seed", "n_src",
    "T_virtual_s", "L_dist_m", "M_measures", "S_switches", "F_clear_fail",
    "N_clear_succ", "closure_s", "closure_residual_s", "closure_ok",
    "cleared", "absent", "unsolved", "failed", "completion_status",
    "completed_successfully", "terminal_reason", "avg_time_per_target_s", "real_time_s",
    "no_signal_measures_total", "no_signal_followups",
    "action_changed_count", "position_changed_count",
    "k_rule_triggered", "model_decisions_used", "model_decision_fallbacks",
    "model_call_fallbacks", "fallback_reason_hist",
    "visited_search_points", "absent_coverage_count", "absent_upper_bound_count",
]


def main():
    records = []
    print("=" * 100)
    print("阶段2 · 四. 预注册 9 局配对验证（P4；seeds 8801/8813/8816；arms A/B/C）")
    print("=" * 100)
    print(f"{'案例':<22} {'臂':<3} {'T(s)':>9} {'L(m)':>9} {'M':>4} {'S':>4} {'F':>3} {'N':>3} "
          f"{'闭合残差':>9} {'清除':>7} {'空频道':>6} {'未决':>4} {'失败':>4} {'现实(s)':>8}")

    for seed, n_src in PREREGISTERED_CASES:
        for arm in ARMS:
            rec = run_one(seed, n_src, arm)
            records.append(rec)
            print(f"{rec['case']:<22} {arm:<3} {rec['T_virtual_s']:>9.2f} "
                  f"{rec['L_dist_m']:>9.1f} {rec['M_measures']:>4} {rec['S_switches']:>4} "
                  f"{rec['F_clear_fail']:>3} {rec['N_clear_succ']:>3} "
                  f"{rec['closure_residual_s']:>9.6f} "
                  f"{rec['cleared']:>3}/{rec['n_src']:<3} {rec['absent']:>6} "
                  f"{rec['unsolved']:>4} {rec['failed']:>4} {rec['real_time_s']:>8.2f}")

    # ---------------- 逐局 CSV ----------------
    csv_path = os.path.join(OUT_DIR, "stage2_paired_9runs.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)

    # ---------------- 验收：先完整清除 ----------------
    print("\n" + "=" * 100)
    print("验收 1：完整清除与计费闭合")
    print("=" * 100)
    accept_ok = True
    for r in records:
        ok = (r["completed_successfully"] and r["unsolved"] == 0 and r["failed"] == 0
              and r["cleared"] == r["n_src"] and r["closure_ok"])
        accept_ok = accept_ok and ok
        print(f"  {r['case']:<22} {r['arm']:<3} 完成={r['completed_successfully']} "
              f"清除={r['cleared']}/{r['n_src']} 未决={r['unsolved']} 失败={r['failed']} "
              f"计费闭合={r['closure_ok']} -> {'PASS' if ok else 'FAIL'}")
    print(f"  全部通过 = {accept_ok}")

    # ---------------- 比较 ----------------
    def pair(a_arm, b_arm):
        rows = []
        for seed, n_src in PREREGISTERED_CASES:
            A = next(r for r in records
                     if r["seed"] == seed and r["arm"] == a_arm)
            B = next(r for r in records
                     if r["seed"] == seed and r["arm"] == b_arm)
            rows.append({"case": A["case"], "A": A["T_virtual_s"], "B": B["T_virtual_s"],
                         "delta": B["T_virtual_s"] - A["T_virtual_s"]})
        d = [x["delta"] for x in rows]
        return {
            "n": len(d),
            "mean_delta": round(statistics.mean(d), 3),
            "median_delta": round(statistics.median(d), 3),
            "worst_regression": round(max(d), 3),
            "best_gain": round(min(d), 3),
            "win": sum(1 for x in d if x < -1e-9),
            "tie": sum(1 for x in d if abs(x) <= 1e-9),
            "loss": sum(1 for x in d if x > 1e-9),
            "per_case": rows,
        }

    summary = {
        "preregistered": PREREGISTERED_CASES,
        "arms": list(ARMS),
        "acceptance_all_pass": accept_ok,
        "C_vs_A": pair("A", "C"),
        "C_vs_B": pair("B", "C"),
        "B_vs_A": pair("A", "B"),
        "records": [{k: v for k, v in r.items()
                     if k not in ("decision_records", "model_update_records",
                                  "per_channel_end_evidence")} for r in records],
    }

    print("\n" + "=" * 100)
    print("验收 2：总虚拟时间比较（负值 = 后者更快）")
    print("=" * 100)
    for name, key in (("C 相对 A", "C_vs_A"), ("C 相对 B", "C_vs_B"), ("B 相对 A", "B_vs_A")):
        p = summary[key]
        print(f"  {name}: 平均 {p['mean_delta']:+.2f}s  中位 {p['median_delta']:+.2f}s  "
              f"最差退步 {p['worst_regression']:+.2f}s  最好 {p['best_gain']:+.2f}s  "
              f"胜/平/负 = {p['win']}/{p['tie']}/{p['loss']}")
        for x in p["per_case"]:
            print(f"      {x['case']:<22} A={x['A']:>9.2f} B={x['B']:>9.2f} Δ={x['delta']:>+9.2f}")

    # ---------------- 汇总 CSV ----------------
    sum_path = os.path.join(OUT_DIR, "stage2_summary.csv")
    with open(sum_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["对比", "案例数", "平均ΔT_s", "中位ΔT_s", "最差退步_s", "最好_s",
                    "胜", "平", "负"])
        for name, key in (("C_vs_A", "C_vs_A"), ("C_vs_B", "C_vs_B"), ("B_vs_A", "B_vs_A")):
            p = summary[key]
            w.writerow([name, p["n"], p["mean_delta"], p["median_delta"],
                        p["worst_regression"], p["best_gain"], p["win"], p["tie"], p["loss"]])

    with open(os.path.join(OUT_DIR, "stage2_paired_9runs.json"), "w",
              encoding="utf-8") as f:
        json.dump({"summary": summary, "records": records}, f,
                  ensure_ascii=False, indent=2, default=str)

    print(f"\n逐局 CSV  -> {csv_path}")
    print(f"汇总 CSV  -> {sum_path}")
    print(f"完整记录  -> {os.path.join(OUT_DIR, 'stage2_paired_9runs.json')}")


if __name__ == "__main__":
    main()
