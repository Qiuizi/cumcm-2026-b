"""
export_two_problem_cases.py - 导出两个问题案例的完整动作日志与决策日志
包含：
1. Case 1: P4-16src-case1 (seed=5600, 16 sources)
2. Case 2: HTTP 日志对应的 15 源实测场景
3. 原始 HTTP 日志精准物理拆解汇总
"""

import sys
import os
import json
import math
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment, RadioSource
from src.strategy_engine import StrategyEngine

class DetailedLoggingDriver:
    def __init__(self, env: SimEnvironment):
        self.env = env
        self.actions = []

    def enter(self):
        res = self.env.enter()
        self.actions.append({
            "seq": len(self.actions) + 1,
            "action": "enter",
            "pos": self.env.cur_pos,
            "channel": self.env.cur_channel,
            "virtual_time_s": self.env.virtual_time_s,
            "res": res,
        })
        return res

    def measure(self, pos: tuple, channel: int):
        p_old = self.env.cur_pos
        ch_old = self.env.cur_channel
        t_old = self.env.virtual_time_s
        res = self.env.measure(pos, channel)
        d_move = math.hypot(pos[0] - p_old[0], pos[1] - p_old[1])
        t_delta = res["virtual_time_s"] - t_old
        self.actions.append({
            "seq": len(self.actions) + 1,
            "action": "measure",
            "from_pos": [round(p_old[0], 2), round(p_old[1], 2)],
            "to_pos": [round(pos[0], 2), round(pos[1], 2)],
            "dist_m": round(d_move, 2),
            "from_channel": ch_old,
            "channel": channel,
            "virtual_time_s": round(res["virtual_time_s"], 2),
            "dt_s": round(t_delta, 2),
            "result": res.get("measure_result"),
            "svd_deg": res.get("svd_deg"),
        })
        return res

    def clear(self, pos: tuple, channel: int):
        p_old = self.env.cur_pos
        ch_old = self.env.cur_channel
        t_old = self.env.virtual_time_s
        res = self.env.clear(pos, channel)
        d_move = math.hypot(pos[0] - p_old[0], pos[1] - p_old[1])
        t_delta = res["virtual_time_s"] - t_old
        self.actions.append({
            "seq": len(self.actions) + 1,
            "action": "clear",
            "from_pos": [round(p_old[0], 2), round(p_old[1], 2)],
            "to_pos": [round(pos[0], 2), round(pos[1], 2)],
            "dist_m": round(d_move, 2),
            "channel": channel,
            "virtual_time_s": round(res["virtual_time_s"], 2),
            "dt_s": round(t_delta, 2),
            "result": res.get("clear_result"),
        })
        return res

    def exit(self):
        res = self.env.exit()
        self.actions.append({
            "seq": len(self.actions) + 1,
            "action": "exit",
            "pos": self.env.cur_pos,
            "virtual_time_s": round(res["virtual_time_s"], 2),
            "res": res,
        })
        return res


def export_case1():
    print(">> 正在导出 Case 1: P4-16src-case1 (seed=5600)...", flush=True)
    env = SimEnvironment.generate_random_case(num_sources=16, is_p4=True, seed=5600)
    drv = DetailedLoggingDriver(env)
    eng = StrategyEngine(driver=drv, is_p4=True, version="C_OPENROUTE", verbose=False)
    res = eng.execute()

    os.makedirs("results/audit_logs", exist_ok=True)
    # 动作日志
    with open("results/audit_logs/case1_seed5600_c_openroute_actions.jsonl", "w", encoding="utf-8") as f:
        for a in drv.actions:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    # 决策日志
    with open("results/audit_logs/case1_seed5600_c_openroute_decisions.json", "w", encoding="utf-8") as f:
        json.dump(eng.decision_logs, f, indent=2, ensure_ascii=False)

    print(f"   Case 1 导出成功! T={res['virtual_time_s']:.2f}s, 清除={res['cleared_count']}/16, 动作数={len(drv.actions)}, 决策数={len(eng.decision_logs)}", flush=True)


def export_case2():
    print(">> 正在导出 Case 2: HTTP 日志对应真实场景...", flush=True)
    sources_data = [
        (9, 198.95, 381.21),
        (8, 504.71, -547.84),
        (10, -168.25, -646.51),
        (12, -358.59, -901.51),
        (5, -503.25, -477.94),
        (19, -744.19, 627.74),
        (1, -895.74, 1275.71),
        (3, -609.99, 1530.78),
        (4, -1532.65, -683.76),
        (7, -1230.01, -607.89),
        (2, -878.52, -1404.11),
        (20, 752.09, 989.95),
        (18, 254.65, 1574.38),
        (16, -1761.92, 128.07),
        (14, 1549.85, -587.63),
    ]
    sources = []
    for ch, x, y in sources_data:
        is_dir = (ch in [14, 9, 10, 4, 16])
        ori = 145.0 if ch == 14 else (65.0 if ch == 9 else 0.0)
        sources.append(RadioSource(ch, x, y, R=1300.0, is_directional=is_dir, orientation_deg=ori))

    env = SimEnvironment(sources)
    drv = DetailedLoggingDriver(env)
    eng = StrategyEngine(driver=drv, is_p4=True, version="C_OPENROUTE", verbose=False)
    res = eng.execute()

    with open("results/audit_logs/case2_http_scene_c_openroute_actions.jsonl", "w", encoding="utf-8") as f:
        for a in drv.actions:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    with open("results/audit_logs/case2_http_scene_c_openroute_decisions.json", "w", encoding="utf-8") as f:
        json.dump(eng.decision_logs, f, indent=2, ensure_ascii=False)

    print(f"   Case 2 导出成功! T={res['virtual_time_s']:.2f}s, 清除={res['cleared_count']}/15, 动作数={len(drv.actions)}, 决策数={len(eng.decision_logs)}", flush=True)


def parse_raw_http_log():
    print(">> 正在精准解析原始 HTTP 实测日志 (results/http_action_log.jsonl)...", flush=True)
    with open("results/http_action_log.jsonl", "r", encoding="utf-8") as f:
        logs = [json.loads(line) for line in f]

    enter_time = logs[0]["timestamp"]
    exit_time = logs[-1]["timestamp"]
    real_duration = exit_time - enter_time
    total_virtual_time = logs[-1]["response"]["virtual_time_s"]

    cleared_channels = []
    measure_count = 0
    clear_fail_count = 0
    clear_succ_count = 0
    total_move_dist = 0.0
    switch_count = 0

    cur_pos = (0.0, 0.0)
    cur_ch = 1

    for l in logs:
        p = l.get("path")
        req = l.get("request", {})
        resp = l.get("response", {})

        if p == "/measure":
            measure_count += 1
            pos = (req["position"]["x"], req["position"]["y"])
            ch = req["channel"]
            d = math.hypot(pos[0] - cur_pos[0], pos[1] - cur_pos[1])
            total_move_dist += d
            cur_pos = pos
            if ch != cur_ch:
                switch_count += 1
                cur_ch = ch
        elif p == "/clear":
            pos = (req["position"]["x"], req["position"]["y"])
            ch = req["channel"]
            d = math.hypot(pos[0] - cur_pos[0], pos[1] - cur_pos[1])
            total_move_dist += d
            cur_pos = pos
            res = resp.get("clear_result")
            if res == "success":
                clear_succ_count += 1
                cleared_channels.append(ch)
            else:
                clear_fail_count += 1

    move_time = total_move_dist / 5.0
    other_time = switch_count * 1.0 + measure_count * 5.0 + clear_fail_count * 3.0 + clear_succ_count * 5.0
    N = len(cleared_channels)

    summary = {
        "raw_record_count": len(logs),
        "cleared_count_N": N,
        "cleared_channels": cleared_channels,
        "wall_clock_real_s": round(real_duration, 2),
        "total_virtual_time_T_s": round(total_virtual_time, 2),
        "avg_time_per_target_T_over_N_s": round(total_virtual_time / N, 2),
        "total_move_dist_m": round(total_move_dist, 1),
        "movement_time_s": round(move_time, 2),
        "movement_time_pct": round(move_time / total_virtual_time * 100, 2),
        "other_actions_time_s": round(other_time, 2),
        "other_actions_time_pct": round(other_time / total_virtual_time * 100, 2),
        "breakdown": {
            "channel_switch_count": switch_count,
            "channel_switch_time_s": switch_count * 1.0,
            "measure_count": measure_count,
            "measure_time_s": measure_count * 5.0,
            "clear_fail_count": clear_fail_count,
            "clear_fail_time_s": clear_fail_count * 3.0,
            "clear_succ_count": clear_succ_count,
            "clear_succ_time_s": clear_succ_count * 5.0,
        }
    }

    with open("results/audit_logs/raw_http_log_exact_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("   原始 HTTP 日志精准解析已输出至 results/audit_logs/raw_http_log_exact_summary.json", flush=True)


if __name__ == "__main__":
    parse_raw_http_log()
    export_case1()
    export_case2()
