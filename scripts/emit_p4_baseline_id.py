"""
emit_p4_baseline_id.py - 生成新的 P4 基线标识（修复后基线）

把修复的提交标识、组件哈希、验收结论与"改了什么/没改什么"固化成一份可核对的标识文件。
"""

import sys
import os
import json
import hashlib
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "results", "p4_fix", "P4_BASELINE_ID.json")

FIX_COMMITS = [
    "fb2de99",  # conservative_grid_frozen.py
    "75f2f16",  # local_decision_frozen.py
    "4557ad5",  # src/strategy_engine.py
]
COMPONENTS = [
    "conservative_grid_frozen.py",
    "local_decision_frozen.py",
    "src/strategy_engine.py",
    "src/conservative_grid.py",
    "src/local_decision.py",
    "src/sim_env.py",
]


def git(*a):
    return subprocess.check_output(["git"] + list(a), cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()


def sha16(rel):
    p = os.path.join(ROOT, rel)
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16] if os.path.exists(p) else "MISSING"


def main():
    acc_path = os.path.join(ROOT, "results", "p4_fix", "fixed_baseline", "acceptance.json")
    acc = json.load(open(acc_path, encoding="utf-8")) if os.path.exists(acc_path) else None
    rows = []
    if acc:
        for r in acc["records"]:
            rows.append({"case_id": r["case_id"], "sources": r["sources"], "seed": r["seed"],
                         "completion_status": r["completion_status"], "cleared": r["cleared"],
                         "unsolved": r["unsolved"], "failed": r["failed_count"],
                         "T_s": round(r["T_s"], 3), "acceptance_pass": r["acceptance_pass"]})

    payload = {
        "baseline_id": "P4-BASELINE-v3.5.0-fix",
        "supersedes": "P4 主线冻结组件快照 (root local_decision_frozen.py / conservative_grid_frozen.py, 2026-09-11 23:38)",
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head_commit": git("rev-parse", "HEAD"),
        "branch_point": git("rev-parse", "master"),
        "branch_point_message": git("log", "-1", "--format=%s", "master"),
        "fix_commits": [{"short": c, "full": git("rev-parse", c), "subject": git("log", "-1", "--format=%s", c)}
                        for c in FIX_COMMITS],
        "component_sha256_16_at_acceptance": {c: sha16(c) for c in COMPONENTS},
        "changed_files": ["conservative_grid_frozen.py", "local_decision_frozen.py", "src/strategy_engine.py"],
        "unchanged": [
            "P4 覆盖点集 (25 点, EvidenceTrackerP4.all_points)",
            "P4 扫描规则 (needs_measure_at)",
            "P4 完成判据 (check_completion + 16 源上限排除)",
            "P4 清除点额外扫描开关 (仍强制关闭)",
            "P3 径向选点 (未迁移到 P4)",
            "共享组件 src/conservative_grid.py 与 src/local_decision.py (保证 P3 合入状态不变)",
        ],
        "guarantees": {
            "prediction_does_not_mutate_real_grid": True,
            "legitimate_observation_keeps_true_cell": True,
            "empty_set_is_not_a_safe_clear_basis": True,
            "model_contradiction_not_reported_as_absent_or_cleared": True,
            "repeated_clear_fail_same_pos_same_state_is_broken": True,
            "budget_exit_distinguished_from_success": True,
        },
        "default_switch_state": {
            "P4 enable_2opt_head": "False (默认关闭，需调用方显式开启)",
            "P3 profile": "stable (径向开关默认关闭)",
        },
        "acceptance": {
            "arm": "fixed_baseline (enable_2opt_head=False)",
            "scenarios": ["P4H-10src-7210", "P4H-13src-7213", "P4H-16src-7216"],
            "passed": (all(r["acceptance_pass"] for r in rows) if rows else None),
            "runs": rows,
            "criteria": ["completion_status==COMPLETED", "cleared==场景源数", "unsolved==0 且 failed==0",
                         "源频道全 CLEARED / 非源频道全 ABSENT", "计费闭合 T=L/5+5M+S+3F+5N",
                         "无网格矛盾事件"],
        },
        "verification_evidence": {
            "minimal_repro_before": "results/p4_fix/diagnosis/minimal_repro_before.json",
            "minimal_repro_after": "results/p4_fix/diagnosis/minimal_repro_after_fix.json",
            "grid_semantics_equivalence": "results/p4_fix/verification/grid_semantics_equivalence.json",
            "p3_unchanged": "results/p4_fix/verification/p3_unchanged_after_p4_fix.json",
        },
        "note": "旧冻结文件与旧失败日志全部保留；本标识仅描述修复后的新基线。",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(json.dumps(payload, indent=2, ensure_ascii=False)[:1800])
    print(f"\n[written] {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
