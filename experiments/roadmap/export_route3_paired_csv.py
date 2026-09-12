"""
export_route3_paired_csv.py —— 把路线3 的配对实验导出为 CSV

输入（均由前序实验生成）：
  results/route3_responsive_stop_results.json   朴素阈值规则 k=1/2/3，P3 与 P4 各 12 案例
  results/route3b_j0_gated_results.json         J0 门控规则 theta=150/250/350/600（仅 P4）

输出：
  route3_paired_cases.csv      逐案例配对明细（基线 / k=1,2,3 / 四个 theta 臂），按问题+源数+seed 排序
  route3_arm_summary.csv       各臂汇总（平均 T、平均 ΔT、胜/平/负、最差/中位/最好 ΔT、清除率、空频道）
"""

import csv
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "results")


def load(name):
    with open(os.path.join(OUT_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    r3 = load("route3_responsive_stop_results.json")
    r3b = load("route3b_j0_gated_results.json")

    baseline = {}
    for rec in r3["baseline"]:
        baseline[(rec["is_p4"], rec["n_src"], rec["seed"])] = rec

    # k 臂
    k_arms = {}
    for rec in r3["variants"]:
        k = rec["stop_after_blind"]
        k_arms.setdefault(k, {})[(rec["is_p4"], rec["n_src"], rec["seed"])] = rec

    # theta 臂（仅 P4）
    th_arms = {}
    for arm in r3b["arms"]:
        th = arm["theta"]
        for rec in arm["rows"]:
            th_arms.setdefault(th, {})[(True, rec["n_src"], rec["seed"])] = rec

    keys = sorted(baseline.keys(), key=lambda k: (k[0], k[1], k[2]))

    # ---------------- 逐案例明细 ----------------
    paired_path = os.path.join(OUT_DIR, "route3_paired_cases.csv")
    with open(paired_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "问题", "源数", "seed", "案例ID",
            "基线_T_s", "基线_盲测次数", "基线_最长盲测链", "基线_盲测链内耗时_s",
            "基线_清除", "基线_空频道", "基线_未决", "基线_失败",
            "k1_T_s", "k1_ΔT_s", "k1_强制清除", "k1_清除", "k1_空频道",
            "k2_T_s", "k2_ΔT_s", "k2_强制清除", "k2_清除", "k2_空频道",
            "k3_T_s", "k3_ΔT_s", "k3_强制清除", "k3_清除", "k3_空频道",
            "θ150_ΔT_s", "θ250_ΔT_s", "θ350_ΔT_s", "θ600_ΔT_s",
        ])
        for key in keys:
            is_p4, n_src, seed = key
            b = baseline[key]
            row = [
                "P4" if is_p4 else "P3", n_src, seed, f"P4-{n_src}src-{seed}" if is_p4
                else f"P3-{n_src}src-{seed}",
                round(b["T"], 2),
                b["blind"]["n_blind_measures"], b["blind"]["max_run_len"],
                round(b["blind"]["waste_beyond_first_s"], 2),
                b["cleared"], b["absent"], b["unsolved"], b["failed"],
            ]
            for k in (1, 2, 3):
                rec = k_arms.get(k, {}).get(key)
                if rec is None:
                    row += ["", "", "", "", ""]
                else:
                    row += [round(rec["T"], 2), round(rec["T"] - b["T"], 2),
                            rec.get("forced_clear_count", 0), rec["cleared"], rec["absent"]]
            for th in (150.0, 250.0, 350.0, 600.0):
                rec = th_arms.get(th, {}).get(key)
                row.append("" if rec is None else round(rec["T"] - b["T"], 2))
            w.writerow(row)

    # ---------------- 各臂汇总 ----------------
    summary_path = os.path.join(OUT_DIR, "route3_arm_summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "臂", "问题", "案例数", "平均T_s", "平均ΔT_s", "胜", "平", "负",
            "最差ΔT_s", "中位ΔT_s", "最好ΔT_s", "清除总数", "源数总数", "空频道总数",
        ])

        def emit(arm_name, tag, pairs):
            """pairs: list of (baseline_T, arm_T, cleared, absent, n_src)"""
            if not pairs:
                return
            dts = [a[1] - a[0] for a in pairs]
            w.writerow([
                arm_name, tag, len(pairs),
                round(statistics.mean(a[1] for a in pairs), 2),
                round(statistics.mean(dts), 2),
                sum(1 for x in dts if x < -1e-9),
                sum(1 for x in dts if abs(x) <= 1e-9),
                sum(1 for x in dts if x > 1e-9),
                round(max(dts), 2), round(statistics.median(dts), 2), round(min(dts), 2),
                sum(a[2] for a in pairs), sum(a[4] for a in pairs), sum(a[3] for a in pairs),
            ])

        for tag in ("P3", "P4"):
            is_p4 = (tag == "P4")
            sel = [k for k in keys if k[0] == is_p4]
            emit("基线", tag, [(baseline[k]["T"], baseline[k]["T"],
                                baseline[k]["cleared"], baseline[k]["absent"], baseline[k]["n_src"])
                               for k in sel])
            for k in (1, 2, 3):
                pairs = []
                for key in sel:
                    rec = k_arms.get(k, {}).get(key)
                    if rec:
                        pairs.append((baseline[key]["T"], rec["T"], rec["cleared"],
                                      rec["absent"], rec["n_src"]))
                emit(f"k={k}", tag, pairs)
        for th in (150.0, 250.0, 350.0, 600.0):
            pairs = []
            for key in [k for k in keys if k[0]]:
                rec = th_arms.get(th, {}).get(key)
                if rec:
                    pairs.append((baseline[key]["T"], rec["T"], rec["cleared"],
                                  rec["absent"], rec["n_src"]))
            emit(f"θ={th:.0f}", "P4", pairs)

    print(f"逐案例明细 -> {paired_path}")
    print(f"各臂汇总   -> {summary_path}")
    print(f"共 {len(keys)} 个配对案例（P3 {sum(1 for k in keys if not k[0])} 例，"
          f"P4 {sum(1 for k in keys if k[0])} 例）")


if __name__ == "__main__":
    main()
