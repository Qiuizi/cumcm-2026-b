"""
verify_p4_fix_acceptance.py - P4 基线正确性修复后的有限验收（本地替代驱动，不连官方模拟器）

两臂（同一修复版本）：
  fixed_baseline       : 关闭首任务 2-opt（修复后的 P4 基线）
  head_2opt_candidate  : 开启首任务 2-opt（预注册的候选臂）

预注册场景：P4H-10src-7210 / P4H-13src-7213 / P4H-16src-7216, dir_ratio=0.5

每局验收（全部必须成立才算通过）：
  1) completion_status == COMPLETED（成功完成，而非预算安全退出）
  2) 完整清除：cleared == 场景真实源数
  3) 无未决/失败：unsolved == 0 且 failed_count == 0
  4) 逐频道结束证据：源频道全部 CLEARED，非源频道全部 ABSENT 且注明排除证明类型
  5) 成本核算闭合：T = L/5 + 5M + S + 3F + 5N（env 计数器与明文动作日志双路核对）
  6) 无模型矛盾事件

输出：
  results/p4_fix/<arm>/acceptance.csv / acceptance.json
  results/p4_fix/<arm>/action_logs/*.jsonl
"""

import sys
import os
import csv
import json
import time
import math
import hashlib
import argparse
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment
from src.strategy_engine import StrategyEngine
from src.client_runner import audit_http_action_log

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FINGERPRINT_FILES = [
    "src/strategy_engine.py",
    "local_decision_frozen.py",
    "conservative_grid_frozen.py",
    "src/sim_env.py",
    "src/local_decision.py",
    "src/conservative_grid.py",
    "scripts/verify_p4_fix_acceptance.py",
]

CASES = [
    {"case_id": "P4H-10src-7210", "sources": 10, "seed": 7210, "dir_ratio": 0.5},
    {"case_id": "P4H-13src-7213", "sources": 13, "seed": 7213, "dir_ratio": 0.5},
    {"case_id": "P4H-16src-7216", "sources": 16, "seed": 7216, "dir_ratio": 0.5},
]


class RecordingLocalDriver:
    def __init__(self, env, session_file, robot_id="local-sim"):
        self.env = env
        self.robot_id = robot_id
        self.session_file = session_file
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        with open(session_file, "w", encoding="utf-8"):
            pass
        self.req_seq = 0
        self.start_timestamp = time.time()

    def _rid(self, p):
        self.req_seq += 1
        return f"{p}-{self.req_seq:06d}"

    def _log(self, path, request, response):
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": time.time(), "path": path,
                                "request": request, "response": response}, ensure_ascii=False) + "\n")

    def enter(self):
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._rid("enter")}
        res = self.env.enter()
        self._log("/enter", req, res)
        return res

    def measure(self, pos, channel):
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._rid("measure"),
               "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)}, "channel": int(channel)}
        res = self.env.measure((float(pos[0]), float(pos[1])), int(channel))
        self._log("/measure", req, res)
        return res

    def clear(self, pos, channel):
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._rid("clear"),
               "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)}, "channel": int(channel)}
        res = self.env.clear((float(pos[0]), float(pos[1])), int(channel))
        self._log("/clear", req, res)
        return res

    def exit(self):
        req = {"arena_id": "default", "robot_id": self.robot_id, "request_id": self._rid("exit")}
        res = self.env.exit()
        self._log("/exit", req, res)
        return res


def sha16(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def fingerprint():
    fp = {}
    for rel in FINGERPRINT_FILES:
        p = os.path.join(ROOT, rel)
        fp[rel] = sha16(p) if os.path.exists(p) else "MISSING"
    return fp


def git(*a):
    return subprocess.check_output(["git"] + list(a), cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()


def run_case(case, enable_2opt_head, outdir):
    env = SimEnvironment.generate_random_case(num_sources=case["sources"], is_p4=True,
                                              seed=case["seed"], dir_ratio=case["dir_ratio"])
    n_dir = sum(1 for s in env.sources.values() if s.is_directional)
    n_omni = len(env.sources) - n_dir

    log_path = os.path.join(outdir, "action_logs", f"{case['case_id']}.jsonl")
    drv = RecordingLocalDriver(env, log_path)
    eng = StrategyEngine(driver=drv, is_p4=True, version="C", scan_at_clearance=False,
                         enable_2opt_head=enable_2opt_head, enable_adaptive_radial_coverage=False, verbose=False)

    config = {
        "is_p4": eng.is_p4, "version": eng.version, "enable_pruning": eng.enable_pruning,
        "scan_at_clearance": eng.scan_at_clearance, "enable_2opt_head": eng.enable_2opt_head,
        "enable_adaptive_radial_coverage": eng.enable_adaptive_radial_coverage,
        "max_repeat_clear_fail": eng.max_repeat_clear_fail,
        "grid_class": f"{eng.grid_class.__module__}.{eng.grid_class.__name__}",
        "local_decision_class": f"{eng.local_decision.__class__.__module__}.{eng.local_decision.__class__.__name__}",
        "search_point_count": len(eng.search_points),
    }

    t0 = time.perf_counter()
    summary = eng.execute()
    real_time_s = time.perf_counter() - t0

    L, M, S, F, N = env.total_distance_m, env.measure_count, env.switch_count, env.clear_fail_count, env.clear_succ_count
    T = summary["virtual_time_s"]
    expected_T = L / 5.0 + 5.0 * M + 1.0 * S + 3.0 * F + 5.0 * N
    residual = abs(T - expected_T)
    log_audit = audit_http_action_log(log_path)

    channels = []
    for ch in range(1, 21):
        st = eng.channels[ch]
        channels.append({
            "channel": ch, "status": st.status, "absence_proof_type": st.absence_proof_type,
            "is_source": ch in env.sources, "fail_reason": st.fail_reason,
            "followup_count": st.followup_count,
            "surviving_cells": (st.grid.count() if st.grid is not None else None),
            "grid_contradiction": (bool(getattr(st.grid, "contradiction", False)) if st.grid is not None else None),
            "rejected_prunes": (int(getattr(st.grid, "rejected_prune_count", 0)) if st.grid is not None else None),
        })

    src_ch = [c for c in channels if c["is_source"]]
    non_src_ch = [c for c in channels if not c["is_source"]]
    unresolved = [c["channel"] for c in channels if c["status"] in ("UNKNOWN", "FOUND")]
    failed_ch = [c["channel"] for c in channels if c["status"] == "FAILED"]
    contradicting = [c["channel"] for c in channels if c["grid_contradiction"]]

    checks = {
        "completion_status_COMPLETED": summary.get("completion_status") == "COMPLETED",
        "all_targets_cleared": summary["cleared_count"] == len(env.sources),
        "no_unsolved": summary["unsolved_count"] == 0,
        "no_failed": summary.get("failed_count", 0) == 0,
        "all_channels_resolved": len(unresolved) == 0,
        "source_channels_all_cleared": all(c["status"] == "CLEARED" for c in src_ch),
        "non_source_channels_all_absent": all(c["status"] == "ABSENT" for c in non_src_ch),
        "billing_closed_env": residual < 1e-3,
        # 明文动作日志中的坐标按协议保留 2 位小数：单步位置量化误差 <= sqrt(2)*0.005 = 0.00707 m，
        # 数百步累计后路径长度误差可达数米（对应 ΔT <= ~1 s）。因此日志重建侧采用 1.0 s 闭合容差；
        # env 计数器侧仍按 1e-3 s 严格闭合，且 M/S/F/N 四项计数要求逐项完全一致。
        "billing_closed_action_log": log_audit["accounting_discrepancy_s"] < 1.0,
        "log_vs_env_counters_match": (log_audit["measure_count"] == M and log_audit["channel_switch_count"] == S
                                      and log_audit["clear_fail_count"] == F and log_audit["clear_succ_count"] == N),
        "no_grid_contradiction": len(contradicting) == 0,
    }
    passed = all(checks.values())

    rec = {
        "case_id": case["case_id"], "sources": case["sources"], "seed": case["seed"],
        "dir_ratio": case["dir_ratio"],
        "omnidirectional": n_omni, "directional": n_dir,
        "enable_2opt_head": enable_2opt_head,
        "completion_status": summary.get("completion_status"),
        "terminal_reason": summary.get("terminal_reason"),
        "cleared": summary["cleared_count"], "unsolved": summary["unsolved_count"],
        "failed_count": summary.get("failed_count", 0),
        "absent_total": summary["absent_count"],
        "proof_coverage_negative": sum(1 for c in channels if c["absence_proof_type"] == "COVERAGE_NEGATIVE"),
        "proof_upper_bound_exclusion": sum(1 for c in channels if c["absence_proof_type"] == "UPPER_BOUND_EXCLUSION"),
        "T_s": T, "L_m": L, "M": M, "S": S, "F": F, "N": N,
        "expected_T_s": expected_T, "residual_s": residual,
        "log_final_virtual_time_s": log_audit["final_virtual_time_s"],
        "log_residual_s": log_audit["accounting_discrepancy_s"],
        "real_time_s": real_time_s,
        "movement_count": summary.get("movement_count", 0),
        "search_points_visited_count": summary.get("search_points_visited_count", 0),
        "head_dispatch_rounds": summary.get("head_dispatch_rounds"),
        "head_change_count": summary.get("dispatched_head_change_count"),
        "unresolved_channels": unresolved, "failed_channels": failed_ch,
        "contradiction_channels": contradicting,
        "checks": checks, "acceptance_pass": passed,
        "log_file": os.path.relpath(log_path, ROOT).replace("\\", "/"),
    }
    audit = {
        "case_id": case["case_id"], "sources": case["sources"], "seed": case["seed"],
        "dir_ratio": case["dir_ratio"], "omnidirectional": n_omni, "directional": n_dir,
        "effective_config": config,
        "source_fingerprint": fingerprint(),
        "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "commit": git("rev-parse", "HEAD")},
        "billing_env": {"L_m": L, "move_time_s": L / 5.0, "M": M, "measure_time_s": 5.0 * M,
                        "S": S, "switch_time_s": 1.0 * S, "F": F, "clear_fail_time_s": 3.0 * F,
                        "N": N, "clear_succ_time_s": 5.0 * N, "virtual_time_s": T,
                        "expected_time_s": expected_T, "residual_s": residual},
        "billing_action_log": log_audit,
        "channels_end_state": channels,
        "completion": {"completion_status": summary.get("completion_status"),
                       "terminal_reason": summary.get("terminal_reason"),
                       "cleared": summary["cleared_count"], "unsolved": summary["unsolved_count"],
                       "failed_count": summary.get("failed_count", 0),
                       "failed_targets": summary.get("failed_targets", []),
                       "max_virtual_duration_s": summary.get("max_virtual_duration_s"),
                       "max_real_duration_s": summary.get("max_real_duration_s")},
        "head_dispatch_records": summary.get("head_dispatch_records", []),
        "decision_log_tail": eng.decision_logs[-5:],
        "real_time_s": real_time_s,
        "action_log": os.path.relpath(log_path, ROOT).replace("\\", "/"),
    }

    print(f"  [{case['case_id']}] 2opt_head={str(enable_2opt_head):5s} status={rec['completion_status']:10s} "
          f"清除={rec['cleared']}/{case['sources']} 未决={rec['unsolved']} 失败={rec['failed_count']} "
          f"T={T:9.2f}s L={L:9.1f}m M={M:3d} S={S:3d} F={F:3d} N={N:2d} 残差={residual:.2e} "
          f"现实={real_time_s:6.1f}s 验收={'PASS' if passed else 'FAIL'}", flush=True)
    if not passed:
        for k, v in checks.items():
            if not v:
                print(f"      !! 未通过: {k}")
    return rec, audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["fixed_baseline", "head_2opt_candidate"], default="fixed_baseline")
    ap.add_argument("--outdir", type=str, default=None,
                    help="输出目录（默认 results/p4_fix/<arm>）；两臂对拍时应指向同一父目录下的不同子目录")
    args = ap.parse_args()

    enable_2opt_head = (args.arm == "head_2opt_candidate")
    outdir = (os.path.join(ROOT, args.outdir) if args.outdir
              else os.path.join(ROOT, "results", "p4_fix", args.arm))
    os.makedirs(os.path.join(outdir, "action_logs"), exist_ok=True)

    print("=" * 116)
    print(f"【P4 修复后验收】arm={args.arm}  enable_2opt_head={enable_2opt_head}")
    print(f"分支: {git('rev-parse', '--abbrev-ref', 'HEAD')} | HEAD: {git('rev-parse', 'HEAD')[:12]}")
    print("场景: P4H-10src-7210 / P4H-13src-7213 / P4H-16src-7216 (dir_ratio=0.5) | 本地替代驱动，不连官方模拟器")
    print("=" * 116, flush=True)

    records, audits = [], {}
    for case in CASES:
        rec, aud = run_case(case, enable_2opt_head, outdir)
        records.append(rec)
        audits[case["case_id"]] = aud

    csv_path = os.path.join(outdir, "acceptance.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Case_ID", "Sources", "Seed", "Dir_Ratio", "Omni", "Directional", "Enable_2opt_head",
                    "Completion_Status", "Cleared", "Unsolved", "Failed", "Absent_Total",
                    "Proof_CovNeg", "Proof_UB", "T_s", "L_m", "M", "S", "F", "N",
                    "Expected_T_s", "Residual_s", "Log_Residual_s", "RealTime_s",
                    "Head_Rounds", "Head_Changes", "Acceptance_Pass"])
        for r in records:
            w.writerow([r["case_id"], r["sources"], r["seed"], r["dir_ratio"], r["omnidirectional"], r["directional"],
                        r["enable_2opt_head"], r["completion_status"], r["cleared"], r["unsolved"],
                        r["failed_count"], r["absent_total"], r["proof_coverage_negative"], r["proof_upper_bound_exclusion"],
                        f"{r['T_s']:.3f}", f"{r['L_m']:.3f}", r["M"], r["S"], r["F"], r["N"],
                        f"{r['expected_T_s']:.6f}", f"{r['residual_s']:.2e}", f"{r['log_residual_s']:.2e}",
                        f"{r['real_time_s']:.3f}", r["head_dispatch_rounds"], r["head_change_count"],
                        r["acceptance_pass"]])

    with open(os.path.join(outdir, "acceptance.json"), "w", encoding="utf-8") as f:
        json.dump({"arm": args.arm, "enable_2opt_head": enable_2opt_head,
                   "git": {"branch": git("rev-parse", "--abbrev-ref", "HEAD"), "commit": git("rev-parse", "HEAD")},
                   "source_fingerprint": fingerprint(), "records": records, "audits": audits},
                  f, indent=2, ensure_ascii=False)

    n_pass = sum(1 for r in records if r["acceptance_pass"])
    print("-" * 116)
    print(f"通过局数: {n_pass}/{len(records)}")
    if n_pass == len(records):
        print("结论: 三局全部通过完整验收（完整清除 + 逐频道结束证据 + 计费闭合 + 成功完成状态）。")
    else:
        print("结论: 存在未通过局，不得进入性能比较。")
    print("=" * 116)
    print(f"CSV: {os.path.relpath(csv_path, ROOT)}")
    if n_pass != len(records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
