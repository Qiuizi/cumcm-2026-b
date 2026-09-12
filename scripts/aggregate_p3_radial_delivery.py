"""
aggregate_p3_radial_delivery.py - P3 径向候选版精简交付：九组配对记录的逐局完整性汇总

原则（严格遵循交付要求）：
1. 只从既有原始记录汇总，不重跑测试、不追加测试局数、不调用官方模拟器。
   原始记录：
     - results/p3_radial_coverage_9cases_summary.csv   (配对 CSV，含现实耗时)
     - results/p3_radial_coverage_9cases_audit.json    (原始审计 JSON，含五类计费明细与径向事件)
2. 原始记录中不存在的字段一律写 "未记录"，既不填 0，也不从耗时反推成功。
3. 逐局核对两件事：
   a) 所有目标是否清除 (成功清除数 == 场景源数)；
   b) 结束证据是否成立 (T 与 L/5+5M+S+3F+5N 的核算残差 < 1e-3)。
4. 汇总结果与原始 CSV 之间做交叉一致性校验 (T、L、M、S、F、N 必须逐位吻合)。

输出：
  results/delivery/p3_radial_per_run_completeness.csv     每局一行 (9 组 × 2 臂 = 18 行)
  results/delivery/p3_radial_per_case_delta.csv           每案例一行配对节省
  results/delivery/p3_radial_field_coverage_audit.json     字段级"已记录/未记录"审计
"""

import sys
import os
import csv
import json

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CSV_PATH = os.path.join(ROOT, "results", "p3_radial_coverage_9cases_summary.csv")
AUDIT_PATH = os.path.join(ROOT, "results", "p3_radial_coverage_9cases_audit.json")
OUT_DIR = os.path.join(ROOT, "results", "delivery")

NOT_RECORDED = "未记录"

GROUP_OF = {
    "P3-Corr-10src-5010": "纠偏三例",
    "P3-Corr-13src-5013": "纠偏三例",
    "P3-Corr-16src-5016": "纠偏三例",
    "P3-New-10src-6010": "新六例",
    "P3-New-10src-6110": "新六例",
    "P3-New-13src-6013": "新六例",
    "P3-New-13src-6113": "新六例",
    "P3-New-16src-6016": "新六例",
    "P3-New-16src-6116": "新六例",
}


def load_csv_pairs():
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        return {row["Case_ID"]: row for row in csv.DictReader(f)}


def fmt(x, nd=6):
    return f"{x:.{nd}f}"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    csv_pairs = load_csv_pairs()
    with open(AUDIT_PATH, "r", encoding="utf-8") as f:
        audits = json.load(f)

    case_ids = list(csv_pairs.keys())
    missing_audit = [c for c in case_ids if c not in audits]
    if missing_audit:
        raise SystemExit(f"审计 JSON 缺少案例: {missing_audit}")

    run_rows = []
    cross_check_failures = []
    field_status = {}

    def mark(field, recorded: bool, case_id, value):
        field_status.setdefault(field, {"recorded": [], "not_recorded": []})
        if recorded:
            field_status[field]["recorded"].append({"case": case_id, "value": value})
        else:
            field_status[field]["not_recorded"].append(case_id)

    for cid in case_ids:
        pair = csv_pairs[cid]
        audit = audits[cid]
        n_src = int(audit["sources"])
        seed = int(audit["seed"])
        group = GROUP_OF.get(cid, "未分类")

        for arm, prefix, arm_label in (
            ("stable", "Base", "stable(稳定基线 v3.4.2, 径向关闭)"),
            ("radial", "Rad", "radial_candidate(径向候选版, 径向开启)"),
        ):
            bil = audit[f"{'base' if arm == 'stable' else 'rad'}_billing"]

            # ---- 原始审计 JSON 已记录的字段 ----
            t_s = bil["virtual_time"]
            L_m = bil["distance_m"]
            M = bil["measure_count"]
            S = bil["switch_count"]
            F = bil["clear_fail_count"]
            N = bil["clear_succ_count"]
            residual = bil["diff_raw"]

            # ---- 配对 CSV 已记录的字段 ----
            real_t = float(pair[f"{prefix}_RealTime_s"])

            # ---- 原始记录中缺失的字段：一律"未记录" ----
            unsolved = NOT_RECORDED              # 原始记录未落盘 unsolved_count
            absent_cov = NOT_RECORDED            # 原始记录未落盘 COVERAGE_NEGATIVE 计数
            absent_ub = NOT_RECORDED             # 原始记录未落盘 UPPER_BOUND_EXCLUSION 计数
            eff_cfg = NOT_RECORDED               # 原始记录未逐局落盘实际生效配置

            # ---- 结束证据 (仅用已记录数据直接判定，不外推) ----
            all_targets_cleared = (N == n_src)
            billing_closed = (abs(residual) < 1e-3)
            evidence = (
                f"成功清除数={N} 与 场景源数={n_src} {'一致(全部目标清除)' if all_targets_cleared else '不一致(存在未清除目标!)'}; "
                f"计费残差={residual:.2e}s {'闭合' if billing_closed else '未闭合!'}; "
                f"未决频道数未落盘, 引擎级全决状态无法从原始记录直接核验"
            )

            # ---- 与配对 CSV 交叉校验 ----
            # 配对 CSV 以固定小数位落盘, 容差取显示精度的半个最小分度
            checks = [
                ("T", t_s, float(pair[f"{prefix}_T_s"]), 0.005),
                ("L", L_m, float(pair[f"{prefix}_Dist_m"]), 0.05),
                ("M", M, int(pair[f"{prefix}_M"]), 0.0),
                ("S", S, int(pair[f"{prefix}_S"]), 0.0),
                ("F", F, int(pair[f"{prefix}_F"]), 0.0),
                ("N", N, int(pair[f"{prefix}_N"]), 0.0),
            ]
            for name, a, b, tol in checks:
                if abs(float(a) - float(b)) > tol + 1e-9:
                    cross_check_failures.append(
                        f"{cid}/{arm}: {name} 审计JSON={a} vs 配对CSV={b} (容差±{tol})"
                    )

            run_rows.append({
                "Case_ID": cid,
                "Group": group,
                "Arm": arm,
                "Arm_Label": arm_label,
                "Sources": n_src,
                "Seed": seed,
                "Cleared": N,
                "Unsolved_Channels": unsolved,
                "Absent_Negative_Coverage": absent_cov,
                "Absent_UpperBound_Exclusion": absent_ub,
                "T_s": fmt(t_s, 3),
                "L_m": fmt(L_m, 3),
                "Measure_Count": M,
                "Switch_Count": S,
                "Fail_Clear_Count": F,
                "Succ_Clear_Count": N,
                "RealTime_s": f"{real_t:.3f}",
                "Billing_Residual_s": fmt(residual, 6),
                "Billing_Closed": billing_closed,
                "All_Targets_Cleared": all_targets_cleared,
                "Completion_Evidence": evidence,
                "Effective_Config_Recorded": eff_cfg,
                "Field_Source": (
                    "T/L/M/S/F/N/残差: 原始审计JSON; 现实耗时: 配对CSV; "
                    "源数/种子: 原始审计JSON; 未决频道数/阴性覆盖排除数/16源上限排除数/实际生效配置: 原始记录未落盘"
                ),
            })

            mark("场景源数", True, cid, n_src)
            mark("成功清除数", True, cid, N)
            mark("未决频道数", False, cid, None)
            mark("阴性覆盖排除数", False, cid, None)
            mark("16源上限排除数", False, cid, None)
            mark("T(总虚拟时间)", True, cid, t_s)
            mark("L(里程)", True, cid, L_m)
            mark("测量次数", True, cid, M)
            mark("切频次数", True, cid, S)
            mark("失败清除次数", True, cid, F)
            mark("现实耗时", True, cid, real_t)
            mark("成本核算残差", True, cid, residual)
            mark("实际生效配置(逐局落盘)", False, cid, None)

    run_csv = os.path.join(OUT_DIR, "p3_radial_per_run_completeness.csv")
    with open(run_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(run_rows[0].keys()))
        writer.writeheader()
        writer.writerows(run_rows)

    # ---------------- 配对增量 (每案例一行) ----------------
    delta_rows = []
    for cid in case_ids:
        pair = csv_pairs[cid]
        audit = audits[cid]
        # 全精度取自原始审计 JSON（配对 CSV 为两位小数落盘, 仅用于交叉核对）
        base_t = audit["base_billing"]["virtual_time"]
        rad_t = audit["rad_billing"]["virtual_time"]
        saved = base_t - rad_t
        if abs(saved - float(pair["Saved_T_s"])) > 0.005 + 1e-9:
            cross_check_failures.append(
                f"{cid}: Saved_T 审计JSON={saved:+.6f} vs 配对CSV={pair['Saved_T_s']}"
            )
        delta_rows.append({
            "Case_ID": cid,
            "Group": GROUP_OF.get(cid, "未分类"),
            "Sources": int(pair["Sources"]),
            "Seed": int(pair["Seed"]),
            "Base_T_s": f"{base_t:.2f}",
            "Rad_T_s": f"{rad_t:.2f}",
            "Saved_T_s": f"{saved:+.2f}",
            "Saved_Pct": f"{(saved / base_t * 100.0):+.3f}%",
            "Verdict": "获益" if saved > 0.05 else ("退步" if saved < -0.05 else "持平"),
            "Base_Dist_m": f"{float(pair['Base_Dist_m']):.1f}",
            "Rad_Dist_m": f"{float(pair['Rad_Dist_m']):.1f}",
            "Saved_Dist_m": f"{float(pair['Saved_Dist_m']):+.1f}",
            "Radial_Adjust_Count": int(pair["Radial_Adjust_Count"]),
            "Billing_Closed": (abs(float(pair["Base_BillDiff_s"])) < 1e-3 and abs(float(pair["Rad_BillDiff_s"])) < 1e-3),
        })

    delta_csv = os.path.join(OUT_DIR, "p3_radial_per_case_delta.csv")
    with open(delta_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(delta_rows[0].keys()))
        writer.writeheader()
        writer.writerows(delta_rows)

    # ---------------- 统计 ----------------
    def stats(rows):
        saved = [float(r["Saved_T_s"]) for r in rows]
        base = [float(r["Base_T_s"]) for r in rows]
        mean_saved = sum(saved) / len(saved)
        mean_base = sum(base) / len(base)
        return {
            "count": len(rows),
            "sum_saved_s": sum(saved),
            "mean_saved_s": mean_saved,
            "mean_base_T_s": mean_base,
            "mean_saved_pct": mean_saved / mean_base * 100.0,
            "wins": sum(1 for s in saved if s > 0.05),
            "ties": sum(1 for s in saved if abs(s) <= 0.05),
            "losses": sum(1 for s in saved if s < -0.05),
            "regressions": [{"case": r["Case_ID"], "saved_T_s": float(r["Saved_T_s"])}
                            for r in rows if float(r["Saved_T_s"]) < -0.05],
        }

    s_new6 = stats([r for r in delta_rows if r["Group"] == "新六例"])
    s_3 = stats([r for r in delta_rows if r["Group"] == "纠偏三例"])
    s_all9 = stats(delta_rows)

    field_audit = {
        "source_records": {
            "paired_csv": os.path.relpath(CSV_PATH, ROOT).replace("\\", "/"),
            "raw_audit_json": os.path.relpath(AUDIT_PATH, ROOT).replace("\\", "/"),
        },
        "cross_check_vs_paired_csv": {
            "checked_fields": ["T", "L", "M", "S", "F", "N"],
            "mismatches": cross_check_failures,
            "passed": len(cross_check_failures) == 0,
        },
        "field_status": {
            k: {
                "recorded_in_all_cases": len(v["not_recorded"]) == 0,
                "recorded_case_count": len(v["recorded"]),
                "not_recorded_case_count": len(v["not_recorded"]),
                "not_recorded_cases": sorted(set(v["not_recorded"])),
            }
            for k, v in field_status.items()
        },
        "no_fabrication_policy": "原始记录中不存在的字段一律写'未记录'，不填0、不由耗时反推成功。",
    }
    with open(os.path.join(OUT_DIR, "p3_radial_field_coverage_audit.json"), "w", encoding="utf-8") as f:
        json.dump(field_audit, f, indent=2, ensure_ascii=False)

    print("=" * 90)
    print("【九组配对记录 · 逐局完整性汇总】")
    print("=" * 90)
    print(f"逐局输出: {os.path.relpath(run_csv, ROOT)}  ({len(run_rows)} 行 = 9 组 × 2 臂)")
    print(f"配对输出: {os.path.relpath(delta_csv, ROOT)}  ({len(delta_rows)} 行)")
    print(f"字段审计: results/delivery/p3_radial_field_coverage_audit.json")
    print("-" * 90)
    print(f"交叉校验 (审计JSON vs 配对CSV, T/L/M/S/F/N): {'全部通过' if not cross_check_failures else '存在不一致'}")
    for m in cross_check_failures:
        print("   !!", m)
    print("-" * 90)
    print("字段级记录状态:")
    for k, v in field_audit["field_status"].items():
        lib = "已记录" if v["recorded_in_all_cases"] else f"未记录({v['not_recorded_case_count']}/18 局)"
        print(f"   {k:<28} {lib}")
    print("-" * 90)
    print("逐局核对 (全部目标清除 / 结束证据):")
    bad = [r for r in run_rows if not (r["All_Targets_Cleared"] and r["Billing_Closed"])]
    print(f"   18 局中 {18 - len(bad)} 局同时满足 [全部目标清除] 且 [计费闭合]；异常 {len(bad)} 局")
    for r in bad:
        print(f"   !! {r['Case_ID']}/{r['Arm']}: {r['Completion_Evidence']}")
    print("-" * 90)
    for label, s in (("新六例", s_new6), ("纠偏三例", s_3), ("九例全集", s_all9)):
        print(f"{label}: n={s['count']} 平均配对节省={s['mean_saved_s']:+.2f}s "
              f"(占基线均值 {s['mean_base_T_s']:.2f}s 的 {s['mean_saved_pct']:+.3f}%) "
              f"胜/平/负={s['wins']}/{s['ties']}/{s['losses']}")
    print("-" * 90)
    print("退步案例保留 (不做机制惩罚):")
    for s in (s_new6, s_3):
        for r in s["regressions"]:
            print(f"   {r['case']}: {r['saved_T_s']:+.2f} s")
    print("=" * 90)

    return {
        "new6": s_new6, "corr3": s_3, "all9": s_all9,
        "cross_check_passed": len(cross_check_failures) == 0,
    }


if __name__ == "__main__":
    main()
