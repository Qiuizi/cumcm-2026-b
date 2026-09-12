"""
export_validation_decisions.py —— 从 validation_12runs.json 导出关键决策记录与回退明细

输出：
  validation_key_decisions.csv   候选版与基线动作/补测点不同的决策（含 J0/Jq、模型状态）
  validation_fallbacks.csv       逐局回退统计与原因分布
"""

from __future__ import annotations

import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(PKG, "results")


def main():
    with open(os.path.join(OUT, "validation_12runs.json"), encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for rec in data["records"]:
        if rec["version"] != "history_candidate":
            continue
        for i, d in enumerate(rec.get("decision_records") or []):
            if not (d.get("action_changed") or d.get("position_changed")):
                continue
            rows.append({
                "case": rec["case"], "seed": rec["seed"], "n_src": rec["n_src"],
                "decision_idx": i, "channel": d.get("channel"),
                "grid_count": d.get("grid_count"),
                "model_usable": d.get("model_usable"),
                "model_alive": d.get("model_alive"),
                "model_n_obs": d.get("model_n_obs"),
                "baseline_action": d.get("baseline_action"),
                "baseline_pos": d.get("baseline_pos"),
                "baseline_J0": d.get("baseline_j0"),
                "baseline_Jq": d.get("baseline_jq"),
                "candidate_action": d.get("candidate_action"),
                "candidate_pos": d.get("candidate_pos"),
                "candidate_J0": d.get("candidate_j0"),
                "candidate_Jq": d.get("candidate_jq"),
                "action_changed": d.get("action_changed"),
                "position_changed": d.get("position_changed"),
            })
    kp = os.path.join(OUT, "validation_key_decisions.csv")
    if rows:
        with open(kp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    else:
        # 本轮逐局记录**没有持久化 decision_records**（launch.run_case 只保留计数），
        # 因此这里不再生成空表，改为在回退明细里报告逐局的"改变动作/换点"计数。
        kp = None

    fr = []
    for rec in data["records"]:
        if rec["version"] != "history_candidate":
            continue
        fr.append({
            "case": rec["case"], "seed": rec["seed"], "n_src": rec["n_src"],
            "decisions_with_model": rec.get("model_decisions_used"),
            "decision_fallbacks": rec.get("model_decision_fallbacks"),
            "call_fallbacks": rec.get("model_call_fallbacks"),
            "model_score_count": rec.get("model_score_count"),
            "fallback_reason_hist": rec.get("fallback_reason_hist"),
            "action_changed": rec.get("action_changed_count"),
            "position_changed": rec.get("position_changed_count"),
            "real_time_s": rec.get("real_time_s"),
        })
    fp = os.path.join(OUT, "validation_fallbacks.csv")
    with open(fp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(fr[0].keys()))
        w.writeheader()
        w.writerows(fr)

    n_act = sum(1 for r in rows if r["action_changed"])
    n_pos = sum(1 for r in rows if r["position_changed"])
    if kp:
        print(f"关键决策记录 -> {kp}   共 {len(rows)} 条"
              f"（动作类型改变 {n_act}，补测点改变 {n_pos}）")
    else:
        print("关键决策记录：本轮未持久化 decision_records（仅保留计数），"
              "逐局计数见下方回退明细")
    print(f"回退明细     -> {fp}   共 {len(fr)} 局")
    for r in fr:
        print(f"  {r['case']:<20} 用模型决策={r['decisions_with_model']:<5} "
              f"整体回退={r['decision_fallbacks']:<5} 逐调用回退={r['call_fallbacks']:<6} "
              f"动作改变={r['action_changed']} 换点={r['position_changed']}")


if __name__ == "__main__":
    main()
