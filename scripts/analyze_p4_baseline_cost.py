"""analyze_p4_baseline_cost.py - 从基线原始动作日志分解 P4 真实成本结构"""
import sys, os, json, math
sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.evidence_tracker import EvidenceTrackerP4

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOGDIR = os.environ.get(
    "P4_BASELINE_LOGDIR",
    os.path.join(ROOT, "results", "p4_local_consistency", "paired_run", "local_scoring_fixed", "action_logs"))
CASES = ["P4H-10src-7210", "P4H-13src-7213", "P4H-16src-7216"]

et = EvidenceTrackerP4()
PTS = [(round(p[0], 2), round(p[1], 2)) for p in et.all_points]
NAMES = ["O"] + [f"A{i}" for i in range(8)] + [f"B{i}" for i in range(16)]


def nearest_search(pos, tol=6.0):
    best, bd = None, 1e9
    for i, p in enumerate(PTS):
        d = math.hypot(pos[0] - p[0], pos[1] - p[1])
        if d < bd:
            bd, best = d, i
    return (best, bd) if bd <= tol else (None, bd)


def analyze(path):
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    seen = set()
    acts = []
    for e in entries:
        if not e.get("response", {}).get("accepted"):
            continue
        rid = e.get("request", {}).get("request_id")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        acts.append(e)
    cur = (0.0, 0.0)
    t_move = t_meas = t_sw = t_fail = t_succ = 0.0
    move_by = {"search": 0.0, "followup": 0.0, "clear": 0.0}
    meas_at_station = {i: 0 for i in range(25)}
    meas_off_station = 0
    per_channel_meas = {}
    station_visit_order = []
    cur_ch = 1
    for e in acts:
        p, req = e["path"], e["request"]
        if p == "/measure":
            pos = (float(req["position"]["x"]), float(req["position"]["y"]))
            ch = int(req["channel"])
            d = math.hypot(pos[0] - cur[0], pos[1] - cur[1])
            t_move += d / 5.0
            si, sd = nearest_search(pos)
            if si is None:
                move_by["followup"] += d / 5.0
                meas_off_station += 1
            else:
                move_by["search"] += d / 5.0
                meas_at_station[si] += 1
                if not station_visit_order or station_visit_order[-1] != si:
                    station_visit_order.append(si)
            if ch != cur_ch:
                t_sw += 1.0
                cur_ch = ch
            t_meas += 5.0
            per_channel_meas[ch] = per_channel_meas.get(ch, 0) + 1
            cur = pos
        elif p == "/clear":
            pos = (float(req["position"]["x"]), float(req["position"]["y"]))
            ch = int(req["channel"])
            d = math.hypot(pos[0] - cur[0], pos[1] - cur[1])
            t_move += d / 5.0
            move_by["clear"] += d / 5.0
            cur = pos
            if e["response"].get("clear_result") == "success":
                t_succ += 5.0
            else:
                t_fail += 3.0
    return {"acts": len(acts), "t_move": t_move, "t_meas": t_meas, "t_sw": t_sw,
            "t_fail": t_fail, "t_succ": t_succ, "move_by": move_by,
            "meas_at_station": meas_at_station, "meas_off_station": meas_off_station,
            "per_channel_meas": per_channel_meas, "station_visit_order": station_visit_order}


print("=" * 108)
print("【P4 基线 (53b664d) 成本结构分解】")
print("=" * 108)
tot = {}
for cid in CASES:
    r = analyze(os.path.join(LOGDIR, f"{cid}.jsonl"))
    T = r["t_move"] + r["t_meas"] + r["t_sw"] + r["t_fail"] + r["t_succ"]
    n_station_visits = sum(1 for i, v in r["meas_at_station"].items() if v > 0)
    print(f"\n{cid}: 动作 {r['acts']}")
    print(f"  T={T:9.2f}s | 移动 {r['t_move']:9.2f} ({r['t_move']/T*100:4.1f}%) | 检测 {r['t_meas']:7.2f} ({r['t_meas']/T*100:4.1f}%) "
          f"| 切频 {r['t_sw']:6.2f} | 失败清除 {r['t_fail']:6.2f} | 成功清除 {r['t_succ']:5.2f}")
    print(f"  移动细分: 搜索段 {r['move_by']['search']:8.2f}s | 定位补测段 {r['move_by']['followup']:8.2f}s | 清除段 {r['move_by']['clear']:8.2f}s")
    print(f"  检测分配: 站内 {sum(r['meas_at_station'].values())} 次 / 站外补测 {r['meas_off_station']} 次")
    print(f"  访问过的搜索点: {n_station_visits}/25")
    order_names = [NAMES[i] for i in r["station_visit_order"]]
    print(f"  访问顺序: {' '.join(order_names)}")
    used = {i: v for i, v in r["meas_at_station"].items() if v > 0}
    print(f"  各站检测次数: " + " ".join(f"{NAMES[i]}={v}" for i, v in sorted(used.items())))
    chs = sorted(r["per_channel_meas"].items())
    print(f"  各频道检测次数: " + " ".join(f"ch{c}:{v}" for c, v in chs))
    tot[cid] = r
print("\n" + "=" * 108)
