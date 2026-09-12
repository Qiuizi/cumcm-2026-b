"""
verify_p4_head_2opt_rigorous.py - P4 首任务 2-opt 单变量配对试验（本地替代驱动，不连官方模拟器）

实验分支唯一变量：
  允许 P4 开放路线的 2-opt 改变最终实际派发的首任务 (enable_2opt_head: False -> True)
其余全部保持不变：覆盖点集(25点)、冻结定位与清除组件(conservative_grid_frozen/local_decision_frozen)、
扫描规则(needs_measure_at)、完成判据(check_completion + 16源上限排除)、清除点额外扫描(P4 强制关闭)、
P3 径向选点(P4 不迁移)。

三个预先固定的场景（运行前写定，未用于任何调参）：
  P4H-10src-7210 / P4H-13src-7213 / P4H-16src-7216, dir_ratio = 0.5

【重要】本轮实测发现：P4 主线代码在该三个场景上均无法正常终止（详见 diagnosis/），
因此本脚本采用"有界运行"（动作上限 ACTION_CAP），把非终止如实记录为 RUNAWAY，
而不是无限运行或伪造成功。完整清除与结束判据按实际结果逐局核对并给出 PASS/FAIL。

每局核对：
  1) 计费闭合: T = L/5 + 5M + S + 3F + 5N
  2) 完整清除: 成功清除数 == 场景真实源数
  3) 结束证据: 20 个频道全部已决(无 UNKNOWN/FOUND)，源频道全 CLEARED，非源频道全 ABSENT
  4) 首任务审计: 逐轮记录 2-opt 前后首任务，统计真正改变下一动作的次数

输出：
  results/p4_head_2opt/p4_head_2opt_paired.csv
  results/p4_head_2opt/p4_head_2opt_audit.json
  results/p4_head_2opt/action_logs/*.jsonl
"""

import sys
import os
import csv
import json
import time
import math
import hashlib
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment
from src.strategy_engine import StrategyEngine
from src.client_runner import audit_http_action_log

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "results", "p4_head_2opt")
LOG_DIR = os.path.join(OUT_DIR, "action_logs")

ACTION_CAP = 1500  # 有界运行上限：超出即判定为非终止（RUNAWAY）

FINGERPRINT_FILES = [
    "src/strategy_engine.py",
    "src/sim_env.py",
    "local_decision_frozen.py",
    "conservative_grid_frozen.py",
    "src/local_decision.py",
    "src/conservative_grid.py",
    "scripts/verify_p4_head_2opt_rigorous.py",
]

CASES = [
    {"case_id": "P4H-10src-7210", "sources": 10, "seed": 7210, "dir_ratio": 0.5},
    {"case_id": "P4H-13src-7213", "sources": 13, "seed": 7213, "dir_ratio": 0.5},
    {"case_id": "P4H-16src-7216", "sources": 16, "seed": 7216, "dir_ratio": 0.5},
]

ARMS = [
    {"arm": "baseline", "enable_2opt_head": False},
    {"arm": "candidate", "enable_2opt_head": True},
]


class RunawayGuard(Exception):
    pass


class RecordingLocalDriver:
    """本地仿真驱动 + 明文动作日志落盘 + 动作上限保护 (格式与 HTTP 驱动一致)"""

    def __init__(self, env: SimEnvironment, session_file: str, cap: int, robot_id: str = "local-sim"):
        self.env = env
        self.robot_id = robot_id
        self.cap = cap
        self.action_count = 0
        self.session_file = session_file
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        with open(session_file, "w", encoding="utf-8"):
            pass
        self.req_seq = 0
        self.start_timestamp = time.time()

    def _next_request_id(self, prefix: str) -> str:
        self.req_seq += 1
        return f"{prefix}-{self.req_seq:06d}"

    def _tick(self):
        self.action_count += 1
        if self.action_count > self.cap:
            raise RunawayGuard(f"action cap {self.cap} exceeded")

    def _log(self, path: str, request: dict, response: dict):
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": time.time(), "path": path,
                                "request": request, "response": response}, ensure_ascii=False) + "\n")

    def enter(self):
        self._tick()
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._next_request_id("enter")}
        res = self.env.enter()
        self._log("/enter", req, res)
        return res

    def measure(self, pos, channel):
        self._tick()
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._next_request_id("measure"),
               "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)}, "channel": int(channel)}
        res = self.env.measure((float(pos[0]), float(pos[1])), int(channel))
        self._log("/measure", req, res)
        return res

    def clear(self, pos, channel):
        self._tick()
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._next_request_id("clear"),
               "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)}, "channel": int(channel)}
        res = self.env.clear((float(pos[0]), float(pos[1])), int(channel))
        self._log("/clear", req, res)
        return res

    def exit(self):
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._next_request_id("exit")}
        res = self.env.exit()
        self._log("/exit", req, res)
        return res


def sha256_norm(path: str) -> tuple:
    with open(path, "rb") as f:
        raw = f.read()
    return (hashlib.sha256(raw).hexdigest()[:16],
            hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()[:16])


def source_fingerprint() -> dict:
    fp = {}
    for rel in FINGERPRINT_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            fp[rel] = {"sha256_raw16": "MISSING", "sha256_lf16": "MISSING"}
            continue
        raw16, lf16 = sha256_norm(p)
        try:
            blob = subprocess.check_output(["git", "hash-object", p], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            blob = "UNKNOWN"
        fp[rel] = {"sha256_raw16": raw16, "sha256_lf16": lf16, "git_blob": blob}
    return fp


def git_rev(rev: str) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", rev], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "UNKNOWN"


def load_action_positions(log_path: str) -> list:
    seen, out = set(), []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            resp = e.get("response", {})
            if not resp.get("accepted"):
                continue
            req = e.get("request", {})
            rid = req.get("request_id")
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            pos_d = req.get("position")
            pos = (float(pos_d["x"]), float(pos_d["y"])) if pos_d else None
            out.append((float(resp.get("virtual_time_s", 0.0)), e.get("path"), pos))
    return out


def run_single(case: dict, arm: dict) -> tuple:
    case_id = case["case_id"]
    env = SimEnvironment.generate_random_case(
        num_sources=case["sources"], is_p4=True, seed=case["seed"], dir_ratio=case["dir_ratio"]
    )
    n_dir = sum(1 for s in env.sources.values() if s.is_directional)
    n_omni = len(env.sources) - n_dir

    log_path = os.path.join(LOG_DIR, f"{case_id}_{arm['arm']}.jsonl")
    driver = RecordingLocalDriver(env, log_path, cap=ACTION_CAP)

    engine = StrategyEngine(
        driver=driver, is_p4=True, version="C", scan_at_clearance=False,
        enable_2opt_head=arm["enable_2opt_head"], enable_adaptive_radial_coverage=False, verbose=False,
    )
    effective_config = {
        "is_p4": engine.is_p4, "version": engine.version, "enable_pruning": engine.enable_pruning,
        "scan_at_clearance": engine.scan_at_clearance, "enable_2opt_head": engine.enable_2opt_head,
        "enable_adaptive_radial_coverage": engine.enable_adaptive_radial_coverage,
        "grid_class": f"{engine.grid_class.__module__}.{engine.grid_class.__name__}",
        "local_decision_class": f"{engine.local_decision.__class__.__module__}.{engine.local_decision.__class__.__name__}",
        "search_point_count": len(engine.search_points),
    }

    t0 = time.perf_counter()
    aborted = False
    try:
        summary = engine.execute()
    except RunawayGuard:
        aborted = True
        summary = {
            "virtual_time_s": engine.virtual_time_s,
            "cleared_count": sum(1 for c in engine.channels.values() if c.status == "CLEARED"),
            "unsolved_count": sum(1 for c in engine.channels.values() if c.status in ("UNKNOWN", "FOUND")),
            "absent_count": sum(1 for c in engine.channels.values() if c.status == "ABSENT"),
            "head_dispatch_records": engine.head_dispatch_records,
            "head_dispatch_rounds": len(engine.head_dispatch_records),
            "dispatched_head_change_count": engine.dispatched_head_change_count,
            "total_2opt_swaps": engine.total_2opt_swaps,
            "movement_count": len(engine.movement_logs),
            "search_points_visited_count": len(engine.search_points_visited),
        }
    real_time_s = time.perf_counter() - t0

    L, M, S, F, N = env.total_distance_m, env.measure_count, env.switch_count, env.clear_fail_count, env.clear_succ_count
    T = summary["virtual_time_s"]
    expected_T = L / 5.0 + 5.0 * M + 1.0 * S + 3.0 * F + 5.0 * N
    residual = abs(T - expected_T)

    log_audit = audit_http_action_log(log_path)

    channels_end = []
    for ch in range(1, 21):
        st = engine.channels[ch]
        channels_end.append({
            "channel": ch, "status": st.status, "absence_proof_type": st.absence_proof_type,
            "is_source": ch in env.sources, "followup_count": st.followup_count,
            "surviving_cells": (st.grid.count() if st.grid is not None else None),
        })

    unresolved = [c["channel"] for c in channels_end if c["status"] in ("UNKNOWN", "FOUND")]
    src_all_cleared = all(c["status"] == "CLEARED" for c in channels_end if c["is_source"])
    non_src_all_absent = all(c["status"] == "ABSENT" for c in channels_end if not c["is_source"])
    proof_cov = sum(1 for c in channels_end if c["absence_proof_type"] == "COVERAGE_NEGATIVE")
    proof_ub = sum(1 for c in channels_end if c["absence_proof_type"] == "UPPER_BOUND_EXCLUSION")

    # 卡死通道诊断：FOUND 且存活单元为 0
    stuck = [c for c in channels_end if c["status"] == "FOUND" and c["surviving_cells"] == 0]

    head_records = summary.get("head_dispatch_records", [])
    changes = [r for r in head_records if r["head_changed"]]
    action_positions = load_action_positions(log_path)
    for r in changes:
        fh, ph = r["final_head"]["pos"], r["pre_head"]["pos"]
        nxt = None
        for vt, p, pos in action_positions:
            if vt > r["virtual_time_s"] + 1e-9 and pos is not None:
                nxt = (p, pos, vt)
                break
        if nxt is None:
            r["next_action"] = None
            r["next_action_matches_final_head"] = None
        else:
            p, pos, vt = nxt
            d_final = math.hypot(pos[0] - fh[0], pos[1] - fh[1])
            d_pre = math.hypot(pos[0] - ph[0], pos[1] - ph[1])
            r["next_action"] = {"path": p, "pos": [round(pos[0], 2), round(pos[1], 2)], "virtual_time_s": vt}
            r["next_action_dist_to_final_head_m"] = round(d_final, 2)
            r["next_action_dist_to_pre_head_m"] = round(d_pre, 2)
            r["next_action_matches_final_head"] = bool(d_final <= d_pre + 1e-6)

    completion = {
        "expected_sources": len(env.sources),
        "cleared": summary["cleared_count"],
        "unsolved": summary["unsolved_count"],
        "aborted_by_action_cap": aborted,
        "action_cap": ACTION_CAP,
        "actions_executed": driver.action_count,
        "all_targets_cleared": summary["cleared_count"] == len(env.sources),
        "all_channels_resolved": len(unresolved) == 0,
        "source_channels_all_cleared": src_all_cleared,
        "non_source_channels_all_absent": non_src_all_absent,
        "unresolved_channels": unresolved,
        "billing_residual_s": residual,
        "billing_closed": residual < 1e-3,
        "log_vs_env_time_match": abs(log_audit["final_virtual_time_s"] - T) < 1e-3,
        "log_vs_env_counter_match": (log_audit["measure_count"] == M and log_audit["channel_switch_count"] == S
                                     and log_audit["clear_fail_count"] == F and log_audit["clear_succ_count"] == N),
        "stuck_channels_zero_cells": [c["channel"] for c in stuck],
    }
    completion["full_acceptance_pass"] = bool(
        completion["all_targets_cleared"] and completion["all_channels_resolved"]
        and completion["source_channels_all_cleared"] and completion["non_source_channels_all_absent"]
        and completion["billing_closed"] and not aborted
    )

    record = {
        "case_id": case_id, "arm": arm["arm"], "sources": case["sources"], "seed": case["seed"],
        "dir_ratio": case["dir_ratio"],
        "source_composition": {"total": len(env.sources), "omnidirectional": n_omni, "directional": n_dir},
        "run_status": "RUNAWAY" if aborted else "NORMAL",
        "effective_config": effective_config,
        "cleared": summary["cleared_count"], "unsolved": summary["unsolved_count"],
        "absent_total": summary["absent_count"],
        "proof_coverage_negative": proof_cov, "proof_upper_bound_exclusion": proof_ub,
        "T_s": T, "L_m": L, "M": M, "S": S, "F": F, "N": N,
        "expected_T_s": expected_T, "residual_s": residual, "real_time_s": real_time_s,
        "head_dispatch_rounds": summary.get("head_dispatch_rounds", 0),
        "head_change_count": summary.get("dispatched_head_change_count", 0),
        "total_2opt_swaps_internal": summary.get("total_2opt_swaps", 0),
        "movement_count": summary.get("movement_count", 0),
        "search_points_visited_count": summary.get("search_points_visited_count", 0),
        "log_file": os.path.relpath(log_path, ROOT).replace("\\", "/"),
        "completion": completion,
    }

    audit_entry = {
        "case_id": case_id, "arm": arm["arm"], "sources": case["sources"], "seed": case["seed"],
        "dir_ratio": case["dir_ratio"], "source_composition": record["source_composition"],
        "run_status": record["run_status"],
        "effective_config": effective_config, "source_fingerprint": source_fingerprint(),
        "git": {"branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT).decode().strip(),
                "commit": git_rev("HEAD")},
        "billing_env": {"L_m": L, "move_time_s": L / 5.0, "M": M, "measure_time_s": 5.0 * M, "S": S,
                        "switch_time_s": 1.0 * S, "F": F, "clear_fail_time_s": 3.0 * F, "N": N,
                        "clear_succ_time_s": 5.0 * N, "virtual_time_s": T, "expected_time_s": expected_T,
                        "residual_s": residual},
        "billing_action_log": log_audit,
        "channels_end_state": channels_end,
        "head_dispatch_records": head_records,
        "completion": completion,
        "real_time_s": real_time_s,
        "action_log": os.path.relpath(log_path, ROOT).replace("\\", "/"),
    }

    print(f"  [{case_id}/{arm['arm']:9s}] 2opt_head={str(arm['enable_2opt_head']):5s} "
          f"状态={record['run_status']:7s} 动作={driver.action_count:5d} 清除={summary['cleared_count']}/{len(env.sources)} "
          f"未决={summary['unsolved_count']:2d} T={T:10.2f}s 残差={residual:.2e} "
          f"首任务轮次={record['head_dispatch_rounds']:2d} 改变={record['head_change_count']:2d} 现实={real_time_s:5.2f}s "
          f"验收={'PASS' if completion['full_acceptance_pass'] else 'FAIL'} "
          f"零单元卡死频道={completion['stuck_channels_zero_cells']}", flush=True)

    return record, audit_entry


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    print("=" * 120)
    print("【P4 首任务 2-opt 单变量配对试验】本地替代驱动，不连接官方模拟器")
    print(f"分支: {subprocess.check_output(['git','rev-parse','--abbrev-ref','HEAD'], cwd=ROOT).decode().strip()} | "
          f"HEAD: {git_rev('HEAD')[:12]} | 主线(master)合入提交: {git_rev('master')[:12]}")
    print(f"唯一变量: enable_2opt_head (P4) False -> True | 有界运行动作上限: {ACTION_CAP}")
    print("=" * 120, flush=True)

    records, audits = [], {}
    for case in CASES:
        for arm in ARMS:
            rec, aud = run_single(case, arm)
            records.append(rec)
            audits[f"{case['case_id']}__{arm['arm']}"] = aud

    csv_path = os.path.join(OUT_DIR, "p4_head_2opt_paired.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "Case_ID", "Sources", "Seed", "Dir_Ratio", "Omni_Sources", "Directional_Sources",
            "Base_Run_Status", "Cand_Run_Status", "Base_Actions", "Cand_Actions",
            "Base_Cleared", "Cand_Cleared", "Base_Unsolved", "Cand_Unsolved",
            "Base_Proof_CovNeg", "Base_Proof_UB", "Cand_Proof_CovNeg", "Cand_Proof_UB",
            "Base_T_s", "Cand_T_s", "Saved_T_s",
            "Base_L_m", "Cand_L_m", "Base_M", "Cand_M", "Base_S", "Cand_S", "Base_F", "Cand_F", "Base_N", "Cand_N",
            "Base_RealTime_s", "Cand_RealTime_s", "Base_Residual_s", "Cand_Residual_s",
            "Base_Head_Rounds", "Base_Head_Changes", "Cand_Head_Rounds", "Cand_Head_Changes",
            "Base_2opt_Internal_Swaps", "Cand_2opt_Internal_Swaps",
            "Base_Stuck_ZeroCell_Channels", "Cand_Stuck_ZeroCell_Channels",
            "Base_Acceptance", "Cand_Acceptance",
        ])
        for case in CASES:
            b = next(r for r in records if r["case_id"] == case["case_id"] and r["arm"] == "baseline")
            c = next(r for r in records if r["case_id"] == case["case_id"] and r["arm"] == "candidate")
            w.writerow([
                case["case_id"], case["sources"], case["seed"], case["dir_ratio"],
                b["source_composition"]["omnidirectional"], b["source_composition"]["directional"],
                b["run_status"], c["run_status"], b["completion"]["actions_executed"], c["completion"]["actions_executed"],
                b["cleared"], c["cleared"], b["unsolved"], c["unsolved"],
                b["proof_coverage_negative"], b["proof_upper_bound_exclusion"],
                c["proof_coverage_negative"], c["proof_upper_bound_exclusion"],
                f"{b['T_s']:.3f}", f"{c['T_s']:.3f}", f"{b['T_s'] - c['T_s']:+.3f}",
                f"{b['L_m']:.3f}", f"{c['L_m']:.3f}", b["M"], c["M"], b["S"], c["S"], b["F"], c["F"], b["N"], c["N"],
                f"{b['real_time_s']:.3f}", f"{c['real_time_s']:.3f}",
                f"{b['residual_s']:.2e}", f"{c['residual_s']:.2e}",
                b["head_dispatch_rounds"], b["head_change_count"], c["head_dispatch_rounds"], c["head_change_count"],
                b["total_2opt_swaps_internal"], c["total_2opt_swaps_internal"],
                "|".join(map(str, b["completion"]["stuck_channels_zero_cells"])),
                "|".join(map(str, c["completion"]["stuck_channels_zero_cells"])),
                b["completion"]["full_acceptance_pass"], c["completion"]["full_acceptance_pass"],
            ])

    audit_path = os.path.join(OUT_DIR, "p4_head_2opt_audit.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audits, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 120)
    print("【逐局验收与配对结果】")
    print("=" * 120)
    all_aborted = all(r["run_status"] == "RUNAWAY" for r in records)
    pass_count = sum(1 for r in records if r["completion"]["full_acceptance_pass"])
    for case in CASES:
        b = next(r for r in records if r["case_id"] == case["case_id"] and r["arm"] == "baseline")
        c = next(r for r in records if r["case_id"] == case["case_id"] and r["arm"] == "candidate")
        print(f"{case['case_id']:18s} 源={case['sources']:2d}(全向{b['source_composition']['omnidirectional']}"
              f"/定向{b['source_composition']['directional']}) "
              f"| 基线 {b['run_status']:7s} 清除={b['cleared']:2d}/{case['sources']} 未决={b['unsolved']:2d} "
              f"首任务改变={b['head_change_count']} | 候选 {c['run_status']:7s} 清除={c['cleared']:2d}/{case['sources']} "
              f"未决={c['unsolved']:2d} 首任务改变={c['head_change_count']} | 验收 {b['completion']['full_acceptance_pass']}/{c['completion']['full_acceptance_pass']}")

    print("-" * 120)
    print(f"六局中通过完整验收的局数: {pass_count}/6")
    print(f"是否全部非终止: {all_aborted}")
    if all_aborted:
        print("结论: 三个场景下基线与候选均无法正常终止（0 个目标被清除），")
        print("      '完整清除与结束证据成立' 的前提不满足，因此【无法给出有效的配对收益结论】。")
    print("=" * 120)
    print(f"配对CSV: {os.path.relpath(csv_path, ROOT)}")
    print(f"审计JSON: {os.path.relpath(audit_path, ROOT)}")
    print(f"原始动作日志目录: {os.path.relpath(LOG_DIR, ROOT)}")


if __name__ == "__main__":
    main()
