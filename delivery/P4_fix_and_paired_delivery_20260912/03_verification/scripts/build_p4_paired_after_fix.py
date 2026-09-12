"""
build_p4_paired_after_fix.py - 修复后 P4 配对结果汇总 + 上一轮失败运行收益字段更正

一、配对比较（严格同一修复版本 = 同一 commit）
    arm A: fixed_baseline      (enable_2opt_head=False)
    arm B: head_2opt_candidate (enable_2opt_head=True)
    收益定义: Saved_T_s = Base_T_s - Cand_T_s（正 = 2-opt 首任务变更带来节省）
    **修复死循环的收益不计入 2-opt 收益**：两臂都在修复后的版本上运行。

二、上一轮六个失败运行的更正
    那六局两臂都未完成（0 目标清除、20 频道未决），当时的 Saved_T_s 是把"动作上限处的
    故障态虚拟时间"相减得到的，不构成性能测量。此处把其 Saved_T_s 更正为 N/A，
    原始动作数据与原始文件原样保留。
"""

import sys
import os
import csv
import json
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PAIR_DIR = os.path.join(ROOT, "results", "p4_fix", "paired_run")
CORR_DIR = os.path.join(ROOT, "results", "p4_fix", "previous_round_corrected")

CASES = ["P4H-10src-7210", "P4H-13src-7213", "P4H-16src-7216"]


def load(arm):
    with open(os.path.join(PAIR_DIR, arm, "acceptance.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    base, cand = load("fixed_baseline"), load("head_2opt_candidate")
    b = {r["case_id"]: r for r in base["records"]}
    c = {r["case_id"]: r for r in cand["records"]}

    same_commit = base["git"]["commit"] == cand["git"]["commit"]

    rows = []
    for cid in CASES:
        rb, rc = b[cid], c[cid]
        saved = rb["T_s"] - rc["T_s"]
        d_move = (rb["L_m"] - rc["L_m"]) / 5.0
        d_meas = 5.0 * (rb["M"] - rc["M"])
        d_sw = 1.0 * (rb["S"] - rc["S"])
        d_fail = 3.0 * (rb["F"] - rc["F"])
        comparable = rb["acceptance_pass"] and rc["acceptance_pass"]
        rows.append({
            "case_id": cid, "sources": rb["sources"], "seed": rb["seed"], "dir_ratio": rb["dir_ratio"],
            "omnidirectional": rb["omnidirectional"], "directional": rb["directional"],
            "base_status": rb["completion_status"], "cand_status": rc["completion_status"],
            "base_cleared": rb["cleared"], "cand_cleared": rc["cleared"],
            "base_unsolved": rb["unsolved"], "cand_unsolved": rc["unsolved"],
            "base_failed": rb["failed_count"], "cand_failed": rc["failed_count"],
            "base_T_s": rb["T_s"], "cand_T_s": rc["T_s"], "saved_T_s": saved,
            "saved_pct": (saved / rb["T_s"] * 100.0),
            "base_L_m": rb["L_m"], "cand_L_m": rc["L_m"],
            "base_M": rb["M"], "cand_M": rc["M"], "base_S": rb["S"], "cand_S": rc["S"],
            "base_F": rb["F"], "cand_F": rc["F"], "base_N": rb["N"], "cand_N": rc["N"],
            "base_real_s": rb["real_time_s"], "cand_real_s": rc["real_time_s"],
            "base_residual_s": rb["residual_s"], "cand_residual_s": rc["residual_s"],
            "base_head_rounds": rb["head_dispatch_rounds"], "base_head_changes": rb["head_change_count"],
            "cand_head_rounds": rc["head_dispatch_rounds"], "cand_head_changes": rc["head_change_count"],
            "contrib_move_s": d_move, "contrib_meas_s": d_meas,
            "contrib_switch_s": d_sw, "contrib_fail_s": d_fail,
            "decomp_sum_s": d_move + d_meas + d_sw + d_fail,
            "comparable": comparable,
            "saved_T_s_field": f"{saved:+.3f}" if comparable else "N/A",
        })

    csv_path = os.path.join(PAIR_DIR, "p4_head_2opt_paired_after_fix.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Case_ID", "Sources", "Seed", "Dir_Ratio", "Omni", "Directional",
                    "Base_Status", "Cand_Status", "Base_Cleared", "Cand_Cleared",
                    "Base_Unsolved", "Cand_Unsolved", "Base_Failed", "Cand_Failed",
                    "Base_T_s", "Cand_T_s", "Saved_T_s", "Saved_Pct",
                    "Base_L_m", "Cand_L_m", "Base_M", "Cand_M", "Base_S", "Cand_S",
                    "Base_F", "Cand_F", "Base_N", "Cand_N",
                    "Base_RealTime_s", "Cand_RealTime_s", "Base_Residual_s", "Cand_Residual_s",
                    "Base_Head_Rounds", "Base_Head_Changes", "Cand_Head_Rounds", "Cand_Head_Changes",
                    "Contrib_Move_s", "Contrib_Meas_s", "Contrib_Switch_s", "Contrib_Fail_s", "Decomp_Sum_s",
                    "Comparable"])
        for r in rows:
            w.writerow([r["case_id"], r["sources"], r["seed"], r["dir_ratio"], r["omnidirectional"], r["directional"],
                        r["base_status"], r["cand_status"], r["base_cleared"], r["cand_cleared"],
                        r["base_unsolved"], r["cand_unsolved"], r["base_failed"], r["cand_failed"],
                        f"{r['base_T_s']:.3f}", f"{r['cand_T_s']:.3f}", r["saved_T_s_field"], f"{r['saved_pct']:+.3f}%",
                        f"{r['base_L_m']:.3f}", f"{r['cand_L_m']:.3f}", r["base_M"], r["cand_M"], r["base_S"], r["cand_S"],
                        r["base_F"], r["cand_F"], r["base_N"], r["cand_N"],
                        f"{r['base_real_s']:.3f}", f"{r['cand_real_s']:.3f}",
                        f"{r['base_residual_s']:.2e}", f"{r['cand_residual_s']:.2e}",
                        r["base_head_rounds"], r["base_head_changes"], r["cand_head_rounds"], r["cand_head_changes"],
                        f"{r['contrib_move_s']:+.3f}", f"{r['contrib_meas_s']:+.3f}",
                        f"{r['contrib_switch_s']:+.3f}", f"{r['contrib_fail_s']:+.3f}", f"{r['decomp_sum_s']:+.3f}",
                        r["comparable"]])

    saved_list = [r["saved_T_s"] for r in rows if r["comparable"]]
    summary = {
        "comparison_scope": "同一修复版本 (同一 commit) 下的 2-opt 首任务开关两臂",
        "base_arm": {"name": "fixed_baseline", "enable_2opt_head": False, "commit": base["git"]["commit"]},
        "cand_arm": {"name": "head_2opt_candidate", "enable_2opt_head": True, "commit": cand["git"]["commit"]},
        "same_commit": same_commit,
        "deadlock_fix_counted_as_2opt_gain": False,
        "n_comparable": len(saved_list),
        "mean_saved_T_s": (sum(saved_list) / len(saved_list)) if saved_list else None,
        "per_case_saved_T_s": {r["case_id"]: r["saved_T_s"] for r in rows},
        "wins_cand_faster": sum(1 for s in saved_list if s > 0.05),
        "losses_cand_slower": sum(1 for s in saved_list if s < -0.05),
        "mean_base_T_s": sum(r["base_T_s"] for r in rows) / len(rows),
        "rows": rows,
    }
    with open(os.path.join(PAIR_DIR, "p4_head_2opt_paired_after_fix.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # ---------------- 上一轮失败运行的收益字段更正 ----------------
    os.makedirs(CORR_DIR, exist_ok=True)
    src_branch = "feature/p4-head-2opt-experiment"
    old_csv_rel = "results/p4_head_2opt/p4_head_2opt_paired.csv"
    corrected_ok = False
    try:
        old_text = subprocess.check_output(["git", "show", f"{src_branch}:{old_csv_rel}"],
                                           cwd=ROOT, stderr=subprocess.DEVNULL).decode("utf-8-sig")
        old_rows = list(csv.DictReader(old_text.splitlines()))
        with open(os.path.join(CORR_DIR, "ORIGINAL_p4_head_2opt_paired.csv"), "w",
                  newline="", encoding="utf-8-sig") as f:
            f.write(old_text)
        corr_rows = []
        for r in old_rows:
            r = dict(r)
            r["Saved_T_s_original"] = r.get("Saved_T_s", "")
            r["Saved_T_s"] = "N/A"
            r["Saved_T_s_Note"] = ("两臂均未完成（0 目标清除 / 20 频道未决）：动作上限处的虚拟时间只用于故障诊断，"
                                   "不构成性能测量")
            corr_rows.append(r)
        fields = list(corr_rows[0].keys())
        with open(os.path.join(CORR_DIR, "p4_head_2opt_paired_corrected.csv"), "w",
                  newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(corr_rows)
        readme = """# 上一轮（修复前）六个失败运行 · 收益字段更正说明

上一轮 \u0060results/p4_head_2opt/p4_head_2opt_paired.csv\u0060 中，三组配对的 6 局全部未完成：
0 个目标清除、20 个频道未决、完整验收 False/False。

该文件中的 \u0060Saved_T_s\u0060 是由两臂在**动作上限处**的故障态虚拟时间相减得到，
只反映"卡死在哪个频道"，**不构成 2-opt 的性能测量**。

本次更正：

- \u0060p4_head_2opt_paired_corrected.csv\u0060：\u0060Saved_T_s\u0060 置为 **N/A**，
  原值移入 \u0060Saved_T_s_original\u0060 列，并新增 \u0060Saved_T_s_Note\u0060 说明；
  其余字段与原始动作数据一字未改。
- \u0060ORIGINAL_p4_head_2opt_paired.csv\u0060：原始文件原样保留，便于追溯。
- 原始动作日志（每局 1500 条）保存在上一轮交付包 \u0060results/p4_head_2opt/action_logs/\u0060，未被修改。
- 修复死循环带来的效果**不计入** 2-opt 收益；本轮 2-opt 收益只在同一修复版本的两臂之间比较。
"""
        with open(os.path.join(CORR_DIR, "README_更正说明.md"), "w", encoding="utf-8") as f:
            f.write(readme)
        corrected_ok = True
    except subprocess.CalledProcessError:
        corrected_ok = False

    print("=" * 118)
    print("【修复后 P4 配对结果】同一修复版本下：2-opt 首任务关闭 vs 开启")
    print("=" * 118)
    print(f"  基线臂 commit = 候选臂 commit ? {same_commit}  ({base['git']['commit'][:12]})")
    print(f"  {'案例':<18} {'基线T':>10} {'候选T':>10} {'Saved_T':>10} {'基线L':>9} {'候选L':>9} "
          f"{'基线F':>6} {'候选F':>6} {'首任务变更':>10}")
    for r in rows:
        print(f"  {r['case_id']:<18} {r['base_T_s']:10.2f} {r['cand_T_s']:10.2f} "
              f"{r['saved_T_s_field']:>10} {r['base_L_m']:9.1f} {r['cand_L_m']:9.1f} "
              f"{r['base_F']:6d} {r['cand_F']:6d} {r['cand_head_changes']:10d}")
    print("-" * 118)
    mean_saved = (sum(saved_list) / len(saved_list)) if saved_list else float("nan")
    print(f"  可比局数 {len(saved_list)}/3；平均 Saved_T = {mean_saved:+.2f} s（正 = 2-opt 更快）")
    print(f"  候选更快 {summary['wins_cand_faster']} 局 / 候选更慢 {summary['losses_cand_slower']} 局")
    print("  **死循环修复的收益未被计入 2-opt 收益**（两臂均在同一修复版本上运行）")
    print("-" * 118)
    print(f"  上一轮失败运行收益字段更正: {'完成' if corrected_ok else '未找到上一轮记录'}")
    print("=" * 118)
    print(f"配对CSV: {os.path.relpath(csv_path, ROOT)}")
    print(f"更正CSV: {os.path.relpath(os.path.join(CORR_DIR, 'p4_head_2opt_paired_corrected.csv'), ROOT)}")


if __name__ == "__main__":
    main()
