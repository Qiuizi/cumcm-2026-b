"""build_p4_cover_redesign_package.py - 组装本轮交付包"""
import sys, os, csv, json, shutil, hashlib, zipfile, subprocess
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG = os.path.join(ROOT, "delivery", "P4_cover_redesign_delivery_20260912")
ZIP = PKG + ".zip"
BASE_REF = "fix/p4-local-scoring-consistency"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def cp(src_rel, dst_rel):
    s, d = os.path.join(ROOT, src_rel), os.path.join(PKG, dst_rel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    if not os.path.exists(s):
        print("  !! missing:", src_rel); return False
    shutil.copy2(s, d); return True


def gitcp(rev, rel, dst_rel):
    d = os.path.join(PKG, dst_rel); os.makedirs(os.path.dirname(d), exist_ok=True)
    try:
        data = subprocess.check_output(["git", "show", f"{rev}:{rel}"], cwd=ROOT, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("  !! git show failed:", rev, rel); return False
    open(d, "wb").write(data); return True


def main():
    os.makedirs(PKG, exist_ok=True)
    # 01_analysis
    cp("results/p4_cover_redesign/cover_cost_exploration.json", "01_analysis/cover_cost_exploration.json")
    cp("results/p4_cover_redesign/lattice_net_exploration.json", "01_analysis/lattice_net_exploration.json")
    cp("results/p4_cover_redesign/net_search.json", "01_analysis/net_search.json")
    cp("results/p4_cover_redesign/cost_budget.json", "01_analysis/cost_budget.json")
    # 02_candidate
    cp("src/evidence_tracker.py", "02_candidate/full_source/src_evidence_tracker.py")
    # geometry certificate
    sys.path.insert(0, ROOT)
    from src.evidence_tracker import EvidenceTrackerP4
    cert = {"candidate_net": "O + 8@990 + 16@1840",
            "baseline_net": "O + 8@999 + 16@1840",
            "candidate_certificate": EvidenceTrackerP4().certificate_geometry(),
            "baseline_certificate": EvidenceTrackerP4(r1=999.0).certificate_geometry()}
    with open(os.path.join(PKG, "02_candidate", "geometry_certificate.json"), "w", encoding="utf-8") as f:
        json.dump(cert, f, ensure_ascii=False, indent=2)
    # 03_scripts
    for s in ["analyze_p4_baseline_cost.py", "explore_p4_cover_cost.py", "explore_p4_lattice_nets.py",
              "search_p4_nets.py", "p4_cost_budget.py", "p4_radius_sensitivity.py",
              "build_p4_cover_redesign_paired.py", "verify_p4_fix_acceptance.py"]:
        cp(f"scripts/{s}", f"03_scripts/{s}")
    # 04_paired_run
    cp("results/p4_cover_redesign/paired_run/p4_cover_redesign_paired.csv", "04_paired_run/p4_cover_redesign_paired.csv")
    cp("results/p4_cover_redesign/paired_run/p4_cover_redesign_paired.json", "04_paired_run/p4_cover_redesign_paired.json")
    cp("results/p4_cover_redesign/paired_run/candidate/acceptance.csv", "04_paired_run/candidate/acceptance.csv")
    cp("results/p4_cover_redesign/paired_run/candidate/acceptance.json", "04_paired_run/candidate/acceptance.json")
    logd = os.path.join(ROOT, "results/p4_cover_redesign/paired_run/candidate/action_logs")
    for fn in sorted(os.listdir(logd)):
        cp(f"results/p4_cover_redesign/paired_run/candidate/action_logs/{fn}", f"04_paired_run/candidate/action_logs/{fn}")
    gitcp(BASE_REF, "results/p4_local_consistency/paired_run/local_scoring_fixed/acceptance.json",
          "04_paired_run/baseline_53b664d/acceptance.json")
    gitcp(BASE_REF, "results/p4_local_consistency/paired_run/local_scoring_fixed/acceptance.csv",
          "04_paired_run/baseline_53b664d/acceptance.csv")
    cp("results/p4_cover_redesign/sensitivity/r1_sensitivity.json", "04_paired_run/sensitivity/r1_sensitivity.json")
    # baseline decomposition text
    # 基线动作日志在 fix/p4-local-scoring-consistency 分支上，取出到临时目录后再做分解
    tmp_logs = os.path.join(ROOT, "results", "p4_cover_redesign", "_baseline_logs")
    os.makedirs(tmp_logs, exist_ok=True)
    try:
        names = subprocess.check_output(
            ["git", "ls-tree", "--name-only",
             f"{BASE_REF}:results/p4_local_consistency/paired_run/local_scoring_fixed/action_logs"],
            cwd=ROOT, stderr=subprocess.DEVNULL).decode().split()
    except subprocess.CalledProcessError:
        names = []
    for fn in names:
        data = subprocess.check_output(
            ["git", "show", f"{BASE_REF}:results/p4_local_consistency/paired_run/local_scoring_fixed/action_logs/{fn}"],
            cwd=ROOT)
        open(os.path.join(tmp_logs, fn), "wb").write(data)
    env = dict(os.environ, P4_BASELINE_LOGDIR=tmp_logs)
    out = subprocess.check_output([sys.executable, os.path.join(ROOT, "scripts/analyze_p4_baseline_cost.py")],
                                  cwd=ROOT, env=env).decode("utf-8", "replace")
    open(os.path.join(PKG, "01_analysis", "baseline_cost_decomposition.txt"), "w", encoding="utf-8").write(out)
    print(out)
    # diff
    os.makedirs(os.path.join(PKG, "02_candidate"), exist_ok=True)
    patch = subprocess.check_output(["git", "-c", "core.quotepath=false", "diff", "53b664d", "HEAD",
                                     "--", "src/evidence_tracker.py"], cwd=ROOT)
    open(os.path.join(PKG, "02_candidate", "source_diff_vs_53b664d.patch"), "wb").write(patch)

    entries = []
    for dp, _d, fs in os.walk(PKG):
        for fn in sorted(fs):
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, PKG).replace("\\", "/")
            if rel == "MANIFEST_文件清单.csv":
                continue
            entries.append({"relative_path": rel, "bytes": os.path.getsize(full), "sha256": sha(full)})
    entries.sort(key=lambda e: e["relative_path"])
    mp = os.path.join(PKG, "MANIFEST_文件清单.csv")
    with open(mp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["relative_path", "bytes", "sha256"]); w.writeheader(); w.writerows(entries)
    entries.append({"relative_path": "MANIFEST_文件清单.csv", "bytes": os.path.getsize(mp), "sha256": sha(mp)})
    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for dp, _d, fs in os.walk(PKG):
            for fn in sorted(fs):
                full = os.path.join(dp, fn)
                zf.write(full, os.path.join(os.path.basename(PKG), os.path.relpath(full, PKG)).replace("\\", "/"))
    with zipfile.ZipFile(ZIP) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]; bad = zf.testzip()
    print("=" * 96)
    print("【P4 覆盖改造 交付包组装完成】")
    print(f"目录: {PKG}")
    print(f"压缩包: {ZIP}  ({os.path.getsize(ZIP):,} 字节)")
    print(f"文件数 {len(entries)} (ZIP {len(names)}) 一致={len(entries)==len(names)} CRC={'OK' if bad is None else bad}")
    for e in entries:
        print(f"  {e['bytes']:>9,}  {e['sha256'][:16]}  {e['relative_path']}")
    print("=" * 96)


if __name__ == "__main__":
    main()
