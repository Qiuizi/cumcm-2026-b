"""
compare_p4_scoring_event.py - 在完全相同的决策状态上对拍"修复前/修复后"的局部评分

修复前的模块（local_decision_frozen.py / conservative_grid_frozen.py）从 58037a3 取出一份副本，
放进隔离目录用子进程加载，保证对拍的是真实的旧实现，而不是重新手写的近似。
新实现直接在进程内调用。两者吃同一个状态（同一网格构造 + 同一 prune 序列 + 同一 cur_p）。

输出：results/p4_local_consistency/scoring_event/scoring_event_ab.json
"""

import sys
import os
import json
import shutil
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "results", "p4_local_consistency", "scoring_event")
OLD_DIR = os.path.join(OUT_DIR, "old_modules_58037a3")
OLD_REV = "58037a3"

STATES = [
    {"label": "S1 大网格/多步计划 cur=(1200,200)", "p1": [999.0, 0.0], "theta1": 0.0, "prunes": [],
     "cur_p": [1200.0, 200.0], "channel": 14, "followup_count": 1, "followup_time_s": 50.0,
     "p1_arg": [999.0, 0.0], "is_p4": True},
    {"label": "S2 大网格/多步计划 cur=(1500,0)", "p1": [999.0, 0.0], "theta1": 0.0, "prunes": [],
     "cur_p": [1500.0, 0.0], "channel": 9, "followup_count": 1, "followup_time_s": 50.0,
     "p1_arg": [999.0, 0.0], "is_p4": True},
    {"label": "S3 大网格/多步计划 cur=(2400,20)", "p1": [999.0, 0.0], "theta1": 0.0, "prunes": [],
     "cur_p": [2400.0, 20.0], "channel": 11, "followup_count": 0, "followup_time_s": 0.0,
     "p1_arg": [999.0, 0.0], "is_p4": True},
    {"label": "S4 Ch14 实测网格 cur=(1840,0)",
     "p1": [999.0, 0.0], "theta1": 36.96,
     "prunes": [{"method": "prune_by_direction", "args": [[1840.0, 0.0], 140.06]}],
     "cur_p": [1840.0, 0.0], "channel": 14, "followup_count": 1, "followup_time_s": 50.0,
     "p1_arg": [999.0, 0.0], "is_p4": True},
    {"label": "S5 大网格 两次测向后 cur=(1600,0)",
     "p1": [999.0, 0.0], "theta1": 0.0,
     "prunes": [{"method": "prune_by_direction", "args": [[2200.0, 0.0], 178.0]},
                {"method": "prune_by_direction", "args": [[1400.0, 900.0], 268.0]}],
     "cur_p": [1600.0, 0.0], "channel": 15, "followup_count": 1, "followup_time_s": 50.0,
     "p1_arg": [999.0, 0.0], "is_p4": True},
]

RUNNER = '''"""在隔离目录内用旧模块评估同一批决策状态"""
import sys, json
import numpy as np
import conservative_grid_frozen as cgf
import local_decision_frozen as ldf

spec_path, out_path = sys.argv[1], sys.argv[2]
states = json.load(open(spec_path, encoding="utf-8"))
out = []
for st in states:
    g = cgf.ConservativeGrid(tuple(st["p1"]), st["theta1"])
    for pr in st["prunes"]:
        getattr(g, pr["method"])(*[tuple(a) if isinstance(a, list) and len(a) == 2 and all(isinstance(x, (int, float)) for x in a) else a for a in pr["args"]])
    try:
        d = ldf.LocalDecisionMaker().decide_action(
            cur_p=tuple(st["cur_p"]), channel=st["channel"], grid=g,
            followup_count=st["followup_count"], followup_time_s=st["followup_time_s"],
            force_clear=False, anchor_a=None, measured_positions=[tuple(st["p1_arg"])],
            cur_channel=st["channel"], is_p4=st["is_p4"], p1=tuple(st["p1_arg"]))
        rec = {"action_type": d["action_type"],
               "position": [round(float(d["position"][0]), 3), round(float(d["position"][1]), 3)],
               "reason": d["reason"],
               "j0": (round(float(d["j0"]), 4) if isinstance(d.get("j0"), (int, float)) else None),
               "best_jq": (round(float(d["best_jq"]), 4) if isinstance(d.get("best_jq"), (int, float)) else None),
               "surviving_cells": int(g.count())}
    except Exception as e:
        rec = {"action_type": "EXCEPTION", "error": f"{type(e).__name__}: {e}"}
    out.append(rec)
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("OK")
'''


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(OLD_DIR, exist_ok=True)
    for fn in ["local_decision_frozen.py", "conservative_grid_frozen.py"]:
        data = subprocess.check_output(["git", "show", f"{OLD_REV}:{fn}"], cwd=ROOT)
        with open(os.path.join(OLD_DIR, fn), "wb") as f:
            f.write(data)
    with open(os.path.join(OLD_DIR, "run_old.py"), "w", encoding="utf-8") as f:
        f.write(RUNNER)

    spec_path = os.path.join(OUT_DIR, "states.json")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(STATES, f, ensure_ascii=False, indent=2)

    old_out = os.path.join(OUT_DIR, "old_results.json")
    subprocess.check_output([sys.executable, os.path.join(OLD_DIR, "run_old.py"), spec_path, old_out],
                            cwd=OLD_DIR)
    with open(old_out, encoding="utf-8") as f:
        old_res = json.load(f)

    # 新实现（进程内，当前工作区）
    import conservative_grid_frozen as cgf
    import local_decision_frozen as ldf
    new_res = []
    for st in STATES:
        g = cgf.ConservativeGrid(tuple(st["p1"]), st["theta1"])
        for pr in st["prunes"]:
            args = []
            for a in pr["args"]:
                args.append(tuple(a) if isinstance(a, list) and len(a) == 2 and all(isinstance(x, (int, float)) for x in a) else a)
            getattr(g, pr["method"])(*args)
        try:
            d = ldf.LocalDecisionMaker().decide_action(
                cur_p=tuple(st["cur_p"]), channel=st["channel"], grid=g,
                followup_count=st["followup_count"], followup_time_s=st["followup_time_s"],
                force_clear=False, anchor_a=None, measured_positions=[tuple(st["p1_arg"])],
                cur_channel=st["channel"], is_p4=st["is_p4"], p1=tuple(st["p1_arg"]))
            new_res.append({"action_type": d["action_type"],
                            "position": [round(float(d["position"][0]), 3), round(float(d["position"][1]), 3)],
                            "reason": d["reason"],
                            "j0": (round(float(d["j0"]), 4) if isinstance(d.get("j0"), (int, float)) else None),
                            "best_jq": (round(float(d["best_jq"]), 4) if isinstance(d.get("best_jq"), (int, float)) else None),
                            "surviving_cells": int(g.count())})
        except Exception as e:
            new_res.append({"action_type": "EXCEPTION", "error": f"{type(e).__name__}: {e}"})

    rows = []
    for st, o, n in zip(STATES, old_res, new_res):
        changed = (o.get("action_type") != n.get("action_type")) or (o.get("position") != n.get("position"))
        rows.append({"state": st["label"], "old": o, "new": n, "action_changed": bool(changed)})

    changed_rows = [r for r in rows if r["action_changed"]]
    payload = {"old_rev": OLD_REV, "states": STATES, "rows": rows,
               "n_states": len(rows), "n_action_changed": len(changed_rows)}

    print("=" * 112)
    print(f"【评分修复 · 同一决策状态对拍】旧实现={OLD_REV} 新实现=当前工作区")
    print("=" * 112)
    for r in rows:
        o, n = r["old"], r["new"]
        print(f"  {r['state']}")
        print(f"      旧: {o.get('action_type')} pos={o.get('position')} j0={o.get('j0')} Jq={o.get('best_jq')} | {str(o.get('reason'))[:52]}")
        print(f"      新: {n.get('action_type')} pos={n.get('position')} j0={n.get('j0')} Jq={n.get('best_jq')} | {str(n.get('reason'))[:52]}")
        print(f"      动作是否改变: {r['action_changed']}")
    print("-" * 112)
    print(f"共 {len(rows)} 个状态，动作发生改变 {len(changed_rows)} 个")
    print("=" * 112)

    with open(os.path.join(OUT_DIR, "scoring_event_ab.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
