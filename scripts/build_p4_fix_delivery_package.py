"""build_p4_fix_delivery_package.py - 组装 P4 修复 + 配对实验交付包"""
import sys, os, csv, json, shutil, hashlib, zipfile, subprocess

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_NAME = "P4_fix_and_paired_delivery_20260912"
PKG_DIR = os.path.join(ROOT, "delivery", PKG_NAME)
ZIP_PATH = os.path.join(ROOT, "delivery", PKG_NAME + ".zip")
PREV_BRANCH = "feature/p4-head-2opt-experiment"


def sha256_of(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def copy_in(src_rel, dst_rel):
    src = os.path.join(ROOT, src_rel)
    dst = os.path.join(PKG_DIR, dst_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.exists(src):
        print(f"  !! missing: {src_rel}")
        return False
    shutil.copy2(src, dst)
    return True


def copy_from_git(rev, git_rel, dst_rel):
    dst = os.path.join(PKG_DIR, dst_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        data = subprocess.check_output(["git", "show", f"{rev}:{git_rel}"], cwd=ROOT, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(f"  !! git show failed: {rev}:{git_rel}")
        return False
    with open(dst, "wb") as f:
        f.write(data)
    return True


def main():
    # ---- 01_root_cause ----
    for rel in ["results/p4_fix/diagnosis/minimal_repro_before.json",
                "results/p4_fix/diagnosis/minimal_repro_after_grid_fix.json",
                "results/p4_fix/diagnosis/minimal_repro_after_fix.json",
                "scripts/diagnose_p4_grid_contradiction.py"]:
        copy_in(rel, "01_root_cause/" + os.path.basename(rel))

    # ---- 02_fix ----
    copy_in("conservative_grid_frozen.py", "02_fix/full_source/conservative_grid_frozen.py")
    copy_in("local_decision_frozen.py", "02_fix/full_source/local_decision_frozen.py")
    copy_in("src/strategy_engine.py", "02_fix/full_source/src_strategy_engine.py")
    copy_in("results/p4_fix/P4_BASELINE_ID.json", "02_fix/P4_BASELINE_ID.json")

    # ---- 03_verification ----
    copy_in("results/p4_fix/fixed_baseline/acceptance.csv", "03_verification/fixed_baseline_acceptance.csv")
    copy_in("results/p4_fix/fixed_baseline/acceptance.json", "03_verification/fixed_baseline_acceptance.json")
    copy_in("results/p4_fix/verification/grid_semantics_equivalence.json", "03_verification/grid_semantics_equivalence.json")
    copy_in("results/p4_fix/verification/p3_unchanged_after_p4_fix.json", "03_verification/p3_unchanged_after_p4_fix.json")
    for s in ["verify_p4_fix_acceptance.py", "verify_p4_grid_semantics_equivalence.py",
              "verify_p3_unchanged_after_p4_fix.py", "build_p4_paired_after_fix.py",
              "emit_p4_baseline_id.py"]:
        copy_in(f"scripts/{s}", f"03_verification/scripts/{s}")

    # ---- 04_paired_run ----
    copy_in("results/p4_fix/paired_run/p4_head_2opt_paired_after_fix.csv", "04_paired_run/p4_head_2opt_paired_after_fix.csv")
    copy_in("results/p4_fix/paired_run/p4_head_2opt_paired_after_fix.json", "04_paired_run/p4_head_2opt_paired_after_fix.json")
    for arm in ["fixed_baseline", "head_2opt_candidate"]:
        copy_in(f"results/p4_fix/paired_run/{arm}/acceptance.csv", f"04_paired_run/{arm}/acceptance.csv")
        copy_in(f"results/p4_fix/paired_run/{arm}/acceptance.json", f"04_paired_run/{arm}/acceptance.json")
        logd = os.path.join(ROOT, "results", "p4_fix", "paired_run", arm, "action_logs")
        for fn in sorted(os.listdir(logd)):
            copy_in(f"results/p4_fix/paired_run/{arm}/action_logs/{fn}", f"04_paired_run/{arm}/action_logs/{fn}")

    # ---- 05_previous_round_corrected ----
    for rel in ["results/p4_fix/previous_round_corrected/p4_head_2opt_paired_corrected.csv",
                "results/p4_fix/previous_round_corrected/ORIGINAL_p4_head_2opt_paired.csv",
                "results/p4_fix/previous_round_corrected/README_更正说明.md"]:
        copy_in(rel, "05_previous_round_corrected/" + os.path.basename(rel))
    prev_logs = subprocess.check_output(["git", "ls-tree", "--name-only", f"{PREV_BRANCH}:results/p4_head_2opt/action_logs"],
                                        cwd=ROOT, stderr=subprocess.DEVNULL).decode().split()
    for fn in prev_logs:
        copy_from_git(PREV_BRANCH, f"results/p4_head_2opt/action_logs/{fn}",
                      f"05_previous_round_corrected/action_logs/{fn}")

    # ---- MANIFEST ----
    entries = []
    for dirpath, _d, files in os.walk(PKG_DIR):
        for fn in sorted(files):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, PKG_DIR).replace("\\", "/")
            if rel == "MANIFEST_文件清单.csv":
                continue
            entries.append({"relative_path": rel, "bytes": os.path.getsize(full), "sha256": sha256_of(full)})
    entries.sort(key=lambda e: e["relative_path"])
    mp = os.path.join(PKG_DIR, "MANIFEST_文件清单.csv")
    with open(mp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["relative_path", "bytes", "sha256"])
        w.writeheader(); w.writerows(entries)
    entries.append({"relative_path": "MANIFEST_文件清单.csv", "bytes": os.path.getsize(mp), "sha256": sha256_of(mp)})

    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _d, files in os.walk(PKG_DIR):
            for fn in sorted(files):
                full = os.path.join(dirpath, fn)
                zf.write(full, os.path.join(PKG_NAME, os.path.relpath(full, PKG_DIR)).replace("\\", "/"))
    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        bad = zf.testzip()

    print("=" * 100)
    print("【P4 修复 + 配对实验 交付包组装完成】")
    print("=" * 100)
    print(f"目录: {PKG_DIR}")
    print(f"压缩包: {ZIP_PATH}  ({os.path.getsize(ZIP_PATH):,} 字节)")
    print(f"文件数 {len(entries)} (ZIP {len(names)}) 一致={len(entries)==len(names)} CRC={'OK' if bad is None else bad}")
    for e in entries:
        print(f"  {e['bytes']:>10,}  {e['sha256'][:16]}  {e['relative_path']}")
    print("=" * 100)


if __name__ == "__main__":
    main()
