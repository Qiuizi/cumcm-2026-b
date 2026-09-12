"""
build_p3_radial_delivery_package.py - 组装 P3 径向候选版精简交付包（含 ZIP）

行为：
1. 由两次本地入口验收落盘 JSON 生成"最终生效配置"（不手工编造配置值）；
2. 把源码差异、验证脚本、原始记录、逐局汇总归档到交付目录；
3. 生成 MANIFEST_文件清单.csv（逐文件 sha256 + 字节数）；
4. 打包为 ZIP 并校验 ZIP 内文件数与清单一致。
"""

import sys
import os
import csv
import json
import shutil
import hashlib
import zipfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG_NAME = "P3_radial_candidate_delivery_v3.4.2"
PKG_DIR = os.path.join(ROOT, "delivery", PKG_NAME)
ZIP_PATH = os.path.join(ROOT, "delivery", PKG_NAME + ".zip")
DELIVERY = os.path.join(ROOT, "results", "delivery")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(rel: str) -> str:
    p = os.path.join(PKG_DIR, rel)
    os.makedirs(p, exist_ok=True)
    return p


def copy_in(src_rel: str, dst_rel: str):
    src = os.path.join(ROOT, src_rel)
    dst = os.path.join(PKG_DIR, dst_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.exists(src):
        print(f"  !! 缺文件, 跳过: {src_rel}")
        return False
    shutil.copy2(src, dst)
    return True


def main():
    os.makedirs(os.path.join(ROOT, "delivery"), exist_ok=True)

    # ---------------- 1. 最终生效配置 ----------------
    with open(os.path.join(DELIVERY, "entry_validation_stable.json"), "r", encoding="utf-8") as f:
        ent_stable = json.load(f)
    with open(os.path.join(DELIVERY, "entry_validation_radial_candidate.json"), "r", encoding="utf-8") as f:
        ent_radial = json.load(f)

    cfg = {
        "baseline": "v3.4.2-guard-upperbound",
        "baseline_git_commit": "160d265",
        "candidate": "v3.4.2+radial (enable_adaptive_radial_coverage=True, 实验特性, 默认关闭)",
        "source_of_truth": (
            "本文件由 scripts/build_p3_radial_delivery_package.py 从两次本地入口验收落盘的 "
            "results/delivery/entry_validation_*.json 自动生成，非手工填写。"
        ),
        "profiles": {
            "stable": {
                "launch": "python scripts/run_port_test.py --prob p3 --version C --profile stable --port 2026 --robot_id <队号>",
                "effective_config": ent_stable["effective_config"],
                "profile_label": ent_stable["profile_label"],
                "source_fingerprint": ent_stable["source_fingerprint"],
            },
            "radial_candidate": {
                "launch": "python scripts/run_port_test.py --prob p3 --version C --profile radial_candidate --port 2026 --robot_id <队号>",
                "effective_config": ent_radial["effective_config"],
                "profile_label": ent_radial["profile_label"],
                "source_fingerprint": ent_radial["source_fingerprint"],
            },
        },
        "invariants": {
            "P3_two_profiles_share_identical_config_except_radial": (
                {k: v for k, v in ent_stable["effective_config"].items() if k != "enable_adaptive_radial_coverage"}
                == {k: v for k, v in ent_radial["effective_config"].items() if k != "enable_adaptive_radial_coverage"}
            ),
            "both_profiles_enable_2opt_head": bool(
                ent_stable["effective_config"]["enable_2opt_head"]
                and ent_radial["effective_config"]["enable_2opt_head"]
            ),
            "radial_default_off_in_stable_profile": (ent_stable["effective_config"]["enable_adaptive_radial_coverage"] is False),
            "source_fingerprint_identical_between_profiles": (ent_stable["source_fingerprint"] == ent_radial["source_fingerprint"]),
            "P4_frozen": "见 03_verification/launch_profile_matrix.json（P4 两档位均为 radial=False, 2opt=False）",
        },
        "entry_acceptance_runs": [
            {
                "profile": "stable",
                "port": ent_stable["scenario"]["port"],
                "external_official_port": ent_stable["scenario"]["external_official_port"],
                "sources": ent_stable["scenario"]["sources_requested"],
                "cleared": ent_stable["summary"]["cleared_count"],
                "unsolved": ent_stable["summary"]["unsolved_count"],
                "absent_coverage": ent_stable["summary"]["absent_coverage_count"],
                "absent_upper_bound": ent_stable["summary"]["absent_upper_bound_count"],
                "radial_adjustments": ent_stable["summary"]["radial_adjustments_count"],
                "billing_residual_s": ent_stable["http_audit"]["accounting_discrepancy_s"],
            },
            {
                "profile": "radial_candidate",
                "port": ent_radial["scenario"]["port"],
                "external_official_port": ent_radial["scenario"]["external_official_port"],
                "sources": ent_radial["scenario"]["sources_requested"],
                "cleared": ent_radial["summary"]["cleared_count"],
                "unsolved": ent_radial["summary"]["unsolved_count"],
                "absent_coverage": ent_radial["summary"]["absent_coverage_count"],
                "absent_upper_bound": ent_radial["summary"]["absent_upper_bound_count"],
                "radial_adjustments": ent_radial["summary"]["radial_adjustments_count"],
                "billing_residual_s": ent_radial["http_audit"]["accounting_discrepancy_s"],
            },
        ],
        "note": "以上两局入口验收使用本地 Mock 服务器与非官方端口 (13026/13027)，不构成九组配对评测样本的一部分。",
    }

    ensure_dir("02_config")
    with open(os.path.join(PKG_DIR, "02_config", "final_effective_config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    BT = chr(96)
    md = ["# 最终生效配置（由入口实跑落盘自动生成）", "",
          "| 配置项 | stable（稳定版） | radial_candidate（径向候选版） |", "|---|---|---|"]
    keys = list(ent_stable["effective_config"].keys())
    for k in keys:
        md.append(f"| {BT}{k}{BT} | {BT}{ent_stable['effective_config'][k]}{BT} | {BT}{ent_radial['effective_config'][k]}{BT} |")
    md += ["", "## 不变量核验", ""]
    for k, v in cfg["invariants"].items():
        md.append(f"- {BT}{k}{BT}: **{v}**")
    md += ["", "## 源码标识（两档位完全一致）", "", "| 文件 | sha256[:16] |", "|---|---|"]
    for k, v in ent_stable["source_fingerprint"].items():
        md.append(f"| {BT}{k}{BT} | {BT}{v}{BT} |")
    md += ["", "## 入口验收实跑（本地 Mock，非官方端口）", "",
           "| 档位 | 端口 | 外部官方端口 | 场景源数 | 成功清除 | 未决频道 | 阴性覆盖排除 | 16源上限排除 | 径向调点 | 计费残差(s) |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in cfg["entry_acceptance_runs"]:
        md.append(f"| {r['profile']} | {r['port']} | {r['external_official_port']} | {r['sources']} | "
                  f"{r['cleared']} | {r['unsolved']} | {r['absent_coverage']} | {r['absent_upper_bound']} | "
                  f"{r['radial_adjustments']} | {r['billing_residual_s']} |")
    md += ["", "> 说明：两局入口验收仅用于验证启动接线与配置落地，源分布为时间随机种子，**不作为收益证据**。", ""]
    with open(os.path.join(PKG_DIR, "02_config", "final_effective_config.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    # ---------------- 2. 归档源码与验证脚本 ----------------
    ensure_dir("01_source_diff/full_source/src")
    ensure_dir("01_source_diff/full_source/scripts")
    ensure_dir("03_verification")
    ensure_dir("04_results")

    copy_in("src/strategy_engine.py", "01_source_diff/full_source/src/strategy_engine.py")
    copy_in("scripts/run_port_test.py", "01_source_diff/full_source/scripts/run_port_test.py")

    ver_files = [
        "scripts/run_port_test.py",
        "scripts/verify_launch_profiles.py",
        "scripts/verify_p3_radial_coverage_rigorous.py",
        "scripts/verify_p3_radial_coverage.py",
        "scripts/aggregate_p3_radial_delivery.py",
        "scripts/build_p3_radial_delivery_package.py",
    ]
    for rel in ver_files:
        copy_in(rel, "03_verification/" + os.path.basename(rel))
    for extra in ["launch_profile_matrix.json",
                  "entry_validation_stable.log", "entry_validation_stable.json",
                  "entry_validation_radial_candidate.log", "entry_validation_radial_candidate.json"]:
        copy_in("results/delivery/" + extra, "03_verification/" + extra)

    res_files = [
        "results/p3_radial_coverage_9cases_summary.csv",
        "results/p3_radial_coverage_6new_cases.csv",
        "results/p3_radial_coverage_3cases_corrected.csv",
        "results/p3_radial_coverage_9cases_audit.json",
        "results/delivery/p3_radial_per_run_completeness.csv",
        "results/delivery/p3_radial_per_case_delta.csv",
        "results/delivery/p3_radial_field_coverage_audit.json",
    ]
    for rel in res_files:
        copy_in(rel, "04_results/" + os.path.basename(rel))

    # ---------------- 3. MANIFEST ----------------
    entries = []
    for dirpath, _dirnames, filenames in os.walk(PKG_DIR):
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, PKG_DIR).replace("\\", "/")
            if rel == "MANIFEST_文件清单.csv":
                continue
            entries.append({
                "relative_path": rel,
                "bytes": os.path.getsize(full),
                "sha256": sha256_of(full),
            })
    entries.sort(key=lambda e: e["relative_path"])

    manifest_path = os.path.join(PKG_DIR, "MANIFEST_文件清单.csv")
    with open(manifest_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["relative_path", "bytes", "sha256"])
        w.writeheader()
        w.writerows(entries)
    entries.append({
        "relative_path": "MANIFEST_文件清单.csv",
        "bytes": os.path.getsize(manifest_path),
        "sha256": sha256_of(manifest_path),
    })

    # ---------------- 4. ZIP ----------------
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(PKG_DIR):
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                arc = os.path.join(PKG_NAME, os.path.relpath(full, PKG_DIR)).replace("\\", "/")
                zf.write(full, arc)

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        bad = zf.testzip()

    print("=" * 88)
    print("【P3 径向候选版 · 精简交付包组装完成】")
    print("=" * 88)
    print(f"交付目录: {PKG_DIR}")
    print(f"压缩包:   {ZIP_PATH}")
    print(f"压缩包大小: {os.path.getsize(ZIP_PATH):,} 字节")
    print(f"目录文件数: {len(entries)} | ZIP 内文件数: {len(names)} | 一致性: {len(entries) == len(names)}")
    print(f"ZIP 完整性(CRC): {'OK' if bad is None else '损坏: ' + str(bad)}")
    print("-" * 88)
    for e in entries:
        print(f"  {e['bytes']:>9,}  {e['sha256'][:16]}  {e['relative_path']}")
    print("=" * 88)


if __name__ == "__main__":
    main()
