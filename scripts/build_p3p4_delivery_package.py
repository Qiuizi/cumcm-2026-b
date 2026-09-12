"""
build_p3p4_delivery_package.py - 组装本轮（P3 合入 + P4 首任务 2-opt 实验）交付包

交付内容：源码差异、实际配置、配对 CSV、原始动作日志、诊断证据、简短结论。
"""

import sys
import os
import csv
import json
import shutil
import hashlib
import zipfile
import subprocess

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_NAME = "P3P4_delivery_20260912"
PKG_DIR = os.path.join(ROOT, "delivery", PKG_NAME)
ZIP_PATH = os.path.join(ROOT, "delivery", PKG_NAME + ".zip")


def git(*args):
    return subprocess.check_output(["git"] + list(args), cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_in(src_rel, dst_rel):
    src = os.path.join(ROOT, src_rel)
    dst = os.path.join(PKG_DIR, dst_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.exists(src):
        print(f"  !! missing, skipped: {src_rel}")
        return False
    shutil.copy2(src, dst)
    return True


def main():
    os.makedirs(PKG_DIR, exist_ok=True)

    # ---- 合并信息 ----
    merge_commit = git("rev-parse", "master")
    payload = {
        "p3_merge": {
            "mainline_branch": "master",
            "merge_commit": merge_commit,
            "merge_commit_short": merge_commit[:7],
            "merge_message": git("log", "-1", "--format=%s", "master"),
            "pre_merge_mainline": git("rev-parse", "master^1"),
            "merged_feature_tip": git("rev-parse", "master^2"),
            "merged_feature_branch": "feature/p3-adaptive-radial-coverage",
            "p3_feature_commits": git("log", "--format=%h %s", "master^1..master^2").splitlines(),
            "merge_strategy": "git merge --no-ff (保留完整分支历史与原始结果)",
            "default_profile_after_merge": "stable (径向开关默认关闭)",
            "radial_candidate_requires": "--profile radial_candidate",
            "statement": "这是代码合入：径向策略没有被设为默认配置。",
        },
        "p4_experiment": {
            "branch": "feature/p4-head-2opt-experiment",
            "branch_point": merge_commit,
            "head": git("rev-parse", "feature/p4-head-2opt-experiment"),
            "commits": git("log", "--format=%h %s", f"{merge_commit}..feature/p4-head-2opt-experiment").splitlines(),
            "single_variable": "enable_2opt_head for P4 (False -> True): allow open-route 2-opt to change the dispatched head task",
            "default_still_off": True,
            "unchanged_components": {
                "P4_coverage_point_count": 25,
                "frozen_components_diff_vs_master": git("diff", "--stat", "master",
                                                        "feature/p4-head-2opt-experiment",
                                                        "--", "local_decision_frozen.py",
                                                        "conservative_grid_frozen.py",
                                                        "src/local_decision.py",
                                                        "src/conservative_grid.py",
                                                        "src/sim_env.py", "src/evidence_tracker.py") or "EMPTY (byte-identical)",
            },
            "source_diff_scope": git("diff", "--stat", "master", "feature/p4-head-2opt-experiment",
                                     "--", "src", "scripts"),
        },
        "verified_facts": {
            "paired_runs_completed": 0,
            "paired_runs_total": 6,
            "all_runs_non_terminating": True,
            "targets_cleared_total": 0,
            "head_change_events_in_candidate_arm": 3,
            "head_gain_conclusion": "无法给出（不满足完整清除与结束证据成立的前提）",
        },
    }
    os.makedirs(os.path.join(PKG_DIR, "01_p3_merge"), exist_ok=True)
    with open(os.path.join(PKG_DIR, "01_p3_merge", "merge_info.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # ---- 01_p3_merge ----
    for rel, dst in [
        ("results/p3_merge_regression/profile_matrix.log", "01_p3_merge/profile_matrix.log"),
        ("results/p3_merge_regression/launch_profile_matrix.json", "01_p3_merge/launch_profile_matrix.json"),
        ("results/p3_merge_regression/entry_stable.log", "01_p3_merge/entry_stable.log"),
        ("results/p3_merge_regression/entry_stable.json", "01_p3_merge/entry_stable.json"),
        ("results/p3_merge_regression/entry_radial_candidate.log", "01_p3_merge/entry_radial_candidate.log"),
        ("results/p3_merge_regression/entry_radial_candidate.json", "01_p3_merge/entry_radial_candidate.json"),
        ("results/p3_merge_regression/entry_default.log", "01_p3_merge/entry_default.log"),
        ("results/p3_merge_regression/entry_default.json", "01_p3_merge/entry_default.json"),
    ]:
        copy_in(rel, dst)

    # ---- 02_p4_experiment ----
    for rel, dst in [
        ("src/strategy_engine.py", "02_p4_experiment/full_source/src/strategy_engine.py"),
        ("results/p4_head_2opt/p4_head_2opt_chain.json", "02_p4_experiment/p4_head_2opt_chain.json"),
        ("results/p4_head_2opt/p4_head_2opt_chain.log", "02_p4_experiment/p4_head_2opt_chain.log"),
        ("results/p4_head_2opt/p4_head_2opt_paired.csv", "02_p4_experiment/p4_head_2opt_paired.csv"),
        ("results/p4_head_2opt/p4_head_2opt_audit.json", "02_p4_experiment/p4_head_2opt_audit.json"),
        ("results/p4_head_2opt/p4_head_2opt_run.log", "02_p4_experiment/p4_head_2opt_run.log"),
        ("results/p4_head_2opt/P4_EXPERIMENT_CONCLUSION.md", "02_p4_experiment/P4_EXPERIMENT_CONCLUSION.md"),
        ("results/p4_head_2opt/diagnosis/p4_nontermination_diagnosis.json", "02_p4_experiment/diagnosis/p4_nontermination_diagnosis.json"),
        ("results/p4_head_2opt/diagnosis/p4_nontermination_diagnosis.log", "02_p4_experiment/diagnosis/p4_nontermination_diagnosis.log"),
        ("results/p4_head_2opt/diagnosis/frozen_vs_shared_components.log", "02_p4_experiment/diagnosis/frozen_vs_shared_components.log"),
        ("scripts/verify_p4_head_2opt_rigorous.py", "02_p4_experiment/scripts/verify_p4_head_2opt_rigorous.py"),
        ("scripts/verify_p4_head_2opt_chain.py", "02_p4_experiment/scripts/verify_p4_head_2opt_chain.py"),
        ("scripts/diagnose_p4_nontermination.py", "02_p4_experiment/scripts/diagnose_p4_nontermination.py"),
        ("scripts/summarize_p4_head_2opt.py", "02_p4_experiment/scripts/summarize_p4_head_2opt.py"),
    ]:
        copy_in(rel, dst)

    log_dir = os.path.join(ROOT, "results", "p4_head_2opt", "action_logs")
    for fn in sorted(os.listdir(log_dir)):
        copy_in(f"results/p4_head_2opt/action_logs/{fn}", f"02_p4_experiment/action_logs/{fn}")

    # ---- MANIFEST ----
    entries = []
    for dirpath, _d, filenames in os.walk(PKG_DIR):
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, PKG_DIR).replace("\\", "/")
            if rel == "MANIFEST_文件清单.csv":
                continue
            entries.append({"relative_path": rel, "bytes": os.path.getsize(full), "sha256": sha256_of(full)})
    entries.sort(key=lambda e: e["relative_path"])
    manifest_path = os.path.join(PKG_DIR, "MANIFEST_文件清单.csv")
    with open(manifest_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["relative_path", "bytes", "sha256"])
        w.writeheader()
        w.writerows(entries)
    entries.append({"relative_path": "MANIFEST_文件清单.csv",
                    "bytes": os.path.getsize(manifest_path), "sha256": sha256_of(manifest_path)})

    # ---- ZIP ----
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _d, filenames in os.walk(PKG_DIR):
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                arc = os.path.join(PKG_NAME, os.path.relpath(full, PKG_DIR)).replace("\\", "/")
                zf.write(full, arc)
    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        bad = zf.testzip()

    print("=" * 96)
    print("【P3 合入 + P4 实验 交付包组装完成】")
    print("=" * 96)
    print(f"P3 合入提交(master): {merge_commit}")
    print(f"P4 实验分支 HEAD:    {git('rev-parse', 'feature/p4-head-2opt-experiment')}")
    print(f"交付目录: {PKG_DIR}")
    print(f"压缩包:   {ZIP_PATH}  ({os.path.getsize(ZIP_PATH):,} 字节)")
    print(f"文件数: {len(entries)} (ZIP {len(names)}) 一致: {len(entries) == len(names)}  CRC: {'OK' if bad is None else bad}")
    print("-" * 96)
    for e in entries:
        print(f"  {e['bytes']:>10,}  {e['sha256'][:16]}  {e['relative_path']}")
    print("=" * 96)


if __name__ == "__main__":
    main()
