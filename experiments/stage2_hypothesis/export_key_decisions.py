"""
export_key_decisions.py —— 导出关键决策记录（阶段2 五. 交付项）

从 results/stage2_paired_9runs.json 中抽取"实际改变动作"的决策记录，写成 CSV：
  - 臂 B：k 规则强制转入清除、且与冻结基线动作不同的决策
  - 臂 C：与冻结基线动作/位置不同的决策
另外导出一份"臂 C 模型状态随观测更新"的轨迹表（逐决策的相容假设数）。
"""

from __future__ import annotations

import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "results")


def main():
    with open(os.path.join(OUT_DIR, "stage2_paired_9runs.json"), encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for rec in data["records"]:
        if rec["arm"] not in ("B", "C"):
            continue
        for i, d in enumerate(rec.get("decision_records") or []):
            if not (d.get("action_changed") or d.get("position_changed")):
                continue
            rows.append({
                "case": rec["case"], "arm": rec["arm"], "decision_idx": i,
                "channel": d.get("channel"),
                "grid_count": d.get("grid_count"),
                "n_obs_at_decision": d.get("n_obs_at_decision", ""),
                "n_alive": d.get("n_alive", ""),
                "frozen_action": d.get("base_action"),
                "frozen_pos": d.get("base_pos"),
                "frozen_J0": d.get("base_j0"),
                "frozen_Jq": d.get("base_jq"),
                "arm_action": d.get("b_action") or d.get("c_action"),
                "arm_pos": d.get("b_pos") or d.get("c_pos"),
                "arm_J0": d.get("c_j0", ""),
                "arm_Jq": d.get("c_jq", ""),
                "action_changed": d.get("action_changed"),
                "position_changed": d.get("position_changed"),
                "reason": d.get("c_reason", ""),
                "p_recv_before_at_frozen_pos": (d.get("recv_probe") or {}).get(
                    "p_recv_before_at_base_pos", ""),
                "p_recv_after_at_frozen_pos": (d.get("recv_probe") or {}).get(
                    "p_recv_after_at_base_pos", ""),
                "p_recv_before_at_arm_pos": (d.get("recv_probe") or {}).get(
                    "p_recv_before_at_c_pos", ""),
                "p_recv_after_at_arm_pos": (d.get("recv_probe") or {}).get(
                    "p_recv_after_at_c_pos", ""),
            })

    path = os.path.join(OUT_DIR, "stage2_key_decisions.csv")
    if rows:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    # 臂 C 的模型更新轨迹
    traj = []
    for rec in data["records"]:
        if rec["arm"] != "C":
            continue
        for u in rec.get("model_update_records") or []:
            traj.append({"case": rec["case"], **u})
    traj_path = os.path.join(OUT_DIR, "stage2_model_updates.csv")
    if traj:
        with open(traj_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(traj[0].keys()))
            w.writeheader()
            w.writerows(traj)

    n_action = sum(1 for r in rows if r["action_changed"])
    n_pos = sum(1 for r in rows if r["position_changed"])
    print(f"关键决策记录 -> {path}")
    print(f"  共 {len(rows)} 条（动作类型改变 {n_action} 条，补测点改变 {n_pos} 条）")
    print(f"模型更新轨迹 -> {traj_path}")
    print(f"  共 {len(traj)} 条（臂 C 逐决策的相容假设数变化）")


if __name__ == "__main__":
    main()
