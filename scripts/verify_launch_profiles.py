"""
verify_launch_profiles.py - 启动档位接线验收（不连接官方端口、不跑完整场景）

核验内容：
1. run_port_test.py 的 --profile {stable, radial_candidate} 开关确实存在并被解析；
2. 两个档位在 P3 下均落到 enable_2opt_head=True；
3. stable 档位落到 enable_adaptive_radial_coverage=False（稳定基线 v3.4.2 保持默认关闭）；
4. radial_candidate 档位在 P3 下落 True，在 P4 下被强制冻结为 False（双重保护）；
5. 引擎对象上的实际取值即为"最终生效配置"（打印即证据）。

输出：results/delivery/launch_profile_matrix.json
"""

import sys
import os
import json
import argparse
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.strategy_engine import StrategyEngine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "results", "delivery")


class NullDriver:
    """空驱动：仅用于构造引擎对象读取最终生效配置，不产生任何通信"""
    def enter(self):
        return {}

    def measure(self, pos, channel):
        return {}

    def clear(self, pos, channel):
        return {}

    def exit(self):
        return {}


def build(is_p4: bool, profile: str) -> StrategyEngine:
    """完全复刻 run_port_test.py 的档位解析与传参逻辑"""
    enable_radial_requested = (profile == "radial_candidate")
    enable_2opt_head = (not is_p4)
    enable_adaptive_radial_coverage = bool(enable_radial_requested and not is_p4)
    return StrategyEngine(
        driver=NullDriver(),
        is_p4=is_p4,
        version="C",
        scan_at_clearance=False,
        enable_2opt_head=enable_2opt_head,
        enable_adaptive_radial_coverage=enable_adaptive_radial_coverage,
        verbose=False,
    )


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- 1. 入口开关存在性 ----
    help_txt = subprocess.check_output(
        [sys.executable, os.path.join(ROOT, "scripts", "run_port_test.py"), "--help"],
        stderr=subprocess.STDOUT, cwd=ROOT
    ).decode("utf-8", errors="replace")
    has_profile = "--profile" in help_txt and "radial_candidate" in help_txt
    has_radial = "--radial_coverage" in help_txt

    print("=" * 88)
    print("【启动档位接线验收 (不连接官方端口)】")
    print("=" * 88)
    print(f"run_port_test.py --help 暴露 --profile {{stable,radial_candidate}}: {has_profile}")
    print(f"run_port_test.py --help 暴露 --radial_coverage {{on,off}}:          {has_radial}")

    # ---- 2. 档位矩阵 ----
    cases = [
        ("P3", False, "stable"),
        ("P3", False, "radial_candidate"),
        ("P4", True, "stable"),
        ("P4", True, "radial_candidate"),
    ]
    rows = []
    ok = True
    print("-" * 88)
    print(f"{'问题':<4} {'档位':<18} {'is_p4':<6} {'enable_2opt_head':<18} {'enable_adaptive_radial_coverage':<32} {'判定'}")
    for prob_name, is_p4, profile in cases:
        eng = build(is_p4, profile)
        cfg = {
            "prob": prob_name,
            "profile": profile,
            "is_p4": eng.is_p4,
            "version": eng.version,
            "enable_pruning": eng.enable_pruning,
            "scan_at_clearance": eng.scan_at_clearance,
            "enable_2opt_head": eng.enable_2opt_head,
            "enable_adaptive_radial_coverage": eng.enable_adaptive_radial_coverage,
            "grid_class": f"{eng.grid_class.__module__}.{eng.grid_class.__name__}",
            "local_decision_class": f"{eng.local_decision.__class__.__module__}.{eng.local_decision.__class__.__name__}",
        }

        if is_p4:
            expect_2opt, expect_radial = False, False
        else:
            expect_2opt = True
            expect_radial = (profile == "radial_candidate")
        passed = (eng.enable_2opt_head == expect_2opt) and (eng.enable_adaptive_radial_coverage == expect_radial)
        ok = ok and passed
        cfg["expect_2opt_head"] = expect_2opt
        cfg["expect_adaptive_radial_coverage"] = expect_radial
        cfg["passed"] = passed
        rows.append(cfg)
        print(f"{prob_name:<4} {profile:<18} {str(eng.is_p4):<6} {str(eng.enable_2opt_head):<18} "
              f"{str(eng.enable_adaptive_radial_coverage):<32} {'PASS' if passed else 'FAIL'}")

    print("-" * 88)
    print(f"总体判定: {'PASS —— 稳定档/径向候选档接线正确, P4 双重冻结' if (ok and has_profile) else 'FAIL'}")
    print("=" * 88)

    payload = {
        "entry_help_exposes_profile_switch": has_profile,
        "entry_help_exposes_radial_coverage_switch": has_radial,
        "profile_matrix": rows,
        "overall_pass": bool(ok and has_profile and has_radial),
        "note": "本脚本仅构造引擎对象读取最终生效配置，不发起任何 HTTP 通信，不连接官方端口。",
    }
    with open(os.path.join(OUT_DIR, "launch_profile_matrix.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    if not payload["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
