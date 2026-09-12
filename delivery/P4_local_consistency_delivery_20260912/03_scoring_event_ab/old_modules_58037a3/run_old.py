"""在隔离目录内用旧模块评估同一批决策状态"""
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
