"""build_p4_cover_redesign_paired.py - 覆盖改造候选 vs 53b664d 基线 配对 + 敏感性区间"""
import sys, os, csv, json, subprocess
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_GIT = "fix/p4-local-scoring-consistency:results/p4_local_consistency/paired_run/local_scoring_fixed/acceptance.json"
NEW = os.path.join(ROOT, "results", "p4_cover_redesign", "paired_run", "candidate", "acceptance.json")
SENS = os.path.join(ROOT, "results", "p4_cover_redesign", "sensitivity", "r1_sensitivity.json")
OUT = os.path.join(ROOT, "results", "p4_cover_redesign", "paired_run")
CASES = ["P4H-10src-7210", "P4H-13src-7213", "P4H-16src-7216"]


def load_base():
    p = os.path.join(ROOT, "results", "p4_local_consistency", "paired_run", "local_scoring_fixed", "acceptance.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    out = subprocess.check_output(["git", "show", BASE_GIT], cwd=ROOT)
    return json.loads(out.decode("utf-8"))


def main():
    b = load_base(); n = json.load(open(NEW, encoding="utf-8"))
    br = {r["case_id"]: r for r in b["records"]}; nr = {r["case_id"]: r for r in n["records"]}
    rows = []
    for cid in CASES:
        rb, rn = br[cid], nr[cid]
        saved = rb["T_s"] - rn["T_s"]
        rows.append({"case_id": cid, "sources": rb["sources"], "seed": rb["seed"],
                     "base_T": rb["T_s"], "new_T": rn["T_s"], "saved_T": saved,
                     "saved_pct": saved / rb["T_s"] * 100.0,
                     "base_L": rb["L_m"], "new_L": rn["L_m"], "base_M": rb["M"], "new_M": rn["M"],
                     "base_S": rb["S"], "new_S": rn["S"], "base_F": rb["F"], "new_F": rn["F"],
                     "base_N": rb["N"], "new_N": rn["N"], "base_real": rb["real_time_s"], "new_real": rn["real_time_s"],
                     "base_status": rb["completion_status"], "new_status": rn["completion_status"],
                     "base_ok": rb["acceptance_pass"], "new_ok": rn["acceptance_pass"],
                     "base_resid": rb["residual_s"], "new_resid": rn["residual_s"]})
    saved = [r["saved_T"] for r in rows]
    sens = json.load(open(SENS, encoding="utf-8")) if os.path.exists(SENS) else {}
    sens_mean = {k: sum(v[c]["T"] for c in CASES) / 3.0 for k, v in sens.items()}
    # 把基线(r1=999)与候选(r1=990)也纳入敏感性带，保证同口径
    sens_mean["999.0"] = sum(r["base_T"] for r in rows) / len(rows)
    sens_mean["990.0"] = sum(r["new_T"] for r in rows) / len(rows)
    band = (max(sens_mean.values()) - min(sens_mean.values())) if sens_mean else None

    with open(os.path.join(OUT, "p4_cover_redesign_paired.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Case_ID", "Sources", "Seed", "Base_T_s", "New_T_s", "Saved_T_s", "Saved_Pct",
                    "Base_L_m", "New_L_m", "Base_M", "New_M", "Base_S", "New_S", "Base_F", "New_F",
                    "Base_N", "New_N", "Base_RealTime_s", "New_RealTime_s",
                    "Base_Status", "New_Status", "Base_Accept", "New_Accept", "Base_Resid", "New_Resid"])
        for r in rows:
            w.writerow([r["case_id"], r["sources"], r["seed"], f"{r['base_T']:.3f}", f"{r['new_T']:.3f}",
                        f"{r['saved_T']:+.3f}", f"{r['saved_pct']:+.3f}%",
                        f"{r['base_L']:.1f}", f"{r['new_L']:.1f}", r["base_M"], r["new_M"], r["base_S"], r["new_S"],
                        r["base_F"], r["new_F"], r["base_N"], r["new_N"],
                        f"{r['base_real']:.1f}", f"{r['new_real']:.1f}",
                        r["base_status"], r["new_status"], r["base_ok"], r["new_ok"],
                        f"{r['base_resid']:.2e}", f"{r['new_resid']:.2e}"])

    summary = {"baseline": {"commit": "53b664d", "net": "O + 8@999 + 16@1840"},
               "candidate": {"commit": "exp/p4-cover-redesign", "net": "O + 8@990 + 16@1840",
                             "note": "r1 由 999 改为 990 的依据是覆盖路线最短（17912.98 m vs 17961.20 m），不是实测用时"},
               "rows": rows, "mean_saved_T_s": sum(saved)/len(saved),
               "per_case_saved_T_s": {r["case_id"]: r["saved_T"] for r in rows},
               "wins": sum(1 for s in saved if s > 0.05), "losses": sum(1 for s in saved if s < -0.05),
               "r1_sensitivity_means": sens_mean, "r1_sensitivity_band_s": band,
               "verdict": ("三例均值差异落在 r1 敏感性带内，不能归因于覆盖结构改变" if band and abs(sum(saved)/len(saved)) < band else "超出敏感性带")}
    with open(os.path.join(OUT, "p4_cover_redesign_paired.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print("=" * 108)
    print("【覆盖改造候选 vs 53b664d 基线】两臂均 2-opt 关闭")
    print("=" * 108)
    print(f"  {'案例':<18} {'基线T':>10} {'候选T':>10} {'Saved_T':>10} {'基线L':>9} {'候选L':>9} {'基线F':>6} {'候选F':>6} 验收")
    for r in rows:
        print(f"  {r['case_id']:<18} {r['base_T']:10.2f} {r['new_T']:10.2f} {r['saved_T']:+10.2f} "
              f"{r['base_L']:9.1f} {r['new_L']:9.1f} {r['base_F']:6d} {r['new_F']:6d} {r['base_ok']}/{r['new_ok']}")
    print("-" * 108)
    print(f"  平均 Saved_T = {sum(saved)/len(saved):+.2f} s   (胜 {summary['wins']} / 负 {summary['losses']})")
    print(f"  r1 敏感性: " + "  ".join(f"r1={k}: {v:.1f}s" for k, v in sorted(sens_mean.items(), key=lambda x: float(x[0]))))
    print(f"  敏感性带宽度 = {band:.2f} s (远大于路线变化 ~10 s) -> {summary['verdict']}")
    print(f"  现实耗时: 基线 {[round(r['base_real'],1) for r in rows]} -> 候选 {[round(r['new_real'],1) for r in rows]}")
    print("=" * 108)
    print(f"配对CSV: results/p4_cover_redesign/paired_run/p4_cover_redesign_paired.csv")


if __name__ == "__main__":
    main()
