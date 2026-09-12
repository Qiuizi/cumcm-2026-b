import csv

p = "experiments/stage2_hypothesis/results/stage2_paired_9runs.csv"
rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
print("阶段2 逐局 no_signal 核对")
print("  no_signal_measures_total = 全部 no_signal 测量次数")
print("  no_signal_followups      = 该频道已发现之后发生的 no_signal 次数")
for case in ["P4-10src-seed8801", "P4-13src-seed8813", "P4-16src-seed8816"]:
    r = {x["arm"]: x for x in rows if x["case"] == case}
    A, B, C = r["A"], r["B"], r["C"]
    print(f"\n  {case}")
    for tag, x in (("A", A), ("B", B), ("C", C)):
        print(f"    {tag}: total={x['no_signal_measures_total']:>4}  "
              f"followup={x['no_signal_followups']:>3}")
    dt = int(A["no_signal_measures_total"]) - int(C["no_signal_measures_total"])
    df = int(A["no_signal_followups"]) - int(C["no_signal_followups"])
    print(f"    A->C：总次数减少={dt}   发现后补测减少={df}   两者相等={dt == df}")
