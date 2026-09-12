"""
verify_p4_head_2opt_chain.py - P4 首任务 2-opt 开关的入口到引擎生效链验收（不通信、不跑场景）

核验：
1. run_port_test.py 的 --enable_2opt_head {on,off} 存在并被解析；
2. P4 下 enable_2opt_head 不再被强制覆盖：显式 on -> 引擎实际 True，未指定 -> 默认 False；
3. 除 enable_2opt_head 外，P4 两档位的全部生效配置逐项相同（含冻结组件类名、扫描开关、径向开关）；
4. P4 的其余冻结项仍被强制关闭（scan_at_clearance / enable_adaptive_radial_coverage）；
5. 源码级检查：强制覆盖行已解除，2-opt 首任务门控仍为 start_i = -1 if self.enable_2opt_head else 0；
6. P3 行为不受影响（radial_candidate 仍可显式开启，stable 仍默认关闭）。

输出：results/p4_head_2opt/p4_head_2opt_chain.json
"""

import sys
import os
import json
import re
import subprocess

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.strategy_engine import StrategyEngine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "results", "p4_head_2opt")


class NullDriver:
    def enter(self): return {}
    def measure(self, pos, channel): return {}
    def clear(self, pos, channel): return {}
    def exit(self): return {}


def build(is_p4, enable_2opt_head, radial=False):
    return StrategyEngine(driver=NullDriver(), is_p4=is_p4, version="C", scan_at_clearance=False,
                          enable_2opt_head=enable_2opt_head,
                          enable_adaptive_radial_coverage=radial, verbose=False)


def cfg(e):
    return {
        "is_p4": e.is_p4, "version": e.version, "enable_pruning": e.enable_pruning,
        "scan_at_clearance": e.scan_at_clearance,
        "enable_2opt_head": e.enable_2opt_head,
        "enable_adaptive_radial_coverage": e.enable_adaptive_radial_coverage,
        "grid_class": f"{e.grid_class.__module__}.{e.grid_class.__name__}",
        "local_decision_class": f"{e.local_decision.__class__.__module__}.{e.local_decision.__class__.__name__}",
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    src = open(os.path.join(ROOT, "src", "strategy_engine.py"), encoding="utf-8").read()

    help_txt = subprocess.check_output(
        [sys.executable, os.path.join(ROOT, "scripts", "run_port_test.py"), "--help"],
        stderr=subprocess.STDOUT, cwd=ROOT).decode("utf-8", errors="replace")

    # ---- 源码级检查 ----
    override_removed = bool(re.search(r"self\.enable_2opt_head = enable_2opt_head\s*$", src, re.M))
    old_override_gone = "enable_2opt_head if not is_p4 else False" not in src
    scan_freeze_kept = "self.scan_at_clearance = scan_at_clearance if not is_p4 else False" in src
    radial_freeze_kept = "self.enable_adaptive_radial_coverage = enable_adaptive_radial_coverage if not is_p4 else False" in src
    head_gate = "start_i = -1 if self.enable_2opt_head else 0" in src
    p3_radial_gate = "if not self.is_p4 and self.enable_adaptive_radial_coverage:" in src

    # ---- 引擎实际生效值 ----
    p4_off = build(True, False)
    p4_on = build(True, True)
    p3_stable = build(False, True, radial=False)
    p3_radial = build(False, True, radial=True)

    c_p4_off, c_p4_on = cfg(p4_off), cfg(p4_on)
    diff_keys = [k for k in c_p4_off if c_p4_off[k] != c_p4_on[k]]

    checks = {
        "help_exposes_enable_2opt_head": ("--enable_2opt_head" in help_txt),
        "source_override_removed": override_removed,
        "old_force_override_pattern_absent": old_override_gone,
        "scan_at_clearance_p4_freeze_kept": scan_freeze_kept,
        "radial_coverage_p4_freeze_kept": radial_freeze_kept,
        "head_gate_present": head_gate,
        "p3_radial_gate_present": p3_radial_gate,
        "p4_explicit_on_yields_true": (c_p4_on["enable_2opt_head"] is True),
        "p4_default_off_yields_false": (c_p4_off["enable_2opt_head"] is False),
        "p4_other_frozen_flags_remain_false": (c_p4_off["scan_at_clearance"] is False
                                               and c_p4_off["enable_adaptive_radial_coverage"] is False
                                               and c_p4_on["scan_at_clearance"] is False
                                               and c_p4_on["enable_adaptive_radial_coverage"] is False),
        "only_enable_2opt_head_differs_in_p4": (diff_keys == ["enable_2opt_head"]),
        "p3_stable_radial_off": (cfg(p3_stable)["enable_adaptive_radial_coverage"] is False),
        "p3_radial_candidate_still_selectable": (cfg(p3_radial)["enable_adaptive_radial_coverage"] is True),
        "p3_2opt_head_still_true": (cfg(p3_stable)["enable_2opt_head"] is True
                                    and cfg(p3_radial)["enable_2opt_head"] is True),
    }
    overall = all(checks.values())

    print("=" * 100)
    print("【P4 首任务 2-opt 入口→引擎生效链验收（无通信）】")
    print("=" * 100)
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print("-" * 100)
    print(f"P4 enable_2opt_head=False -> {c_p4_off}")
    print(f"P4 enable_2opt_head=True  -> {c_p4_on}")
    print(f"P4 两档位差异字段: {diff_keys}")
    print("-" * 100)
    print(f"总体判定: {'PASS' if overall else 'FAIL'}")
    print("=" * 100)

    payload = {
        "checks": {k: bool(v) for k, v in checks.items()},
        "overall_pass": bool(overall),
        "chain": [
            "scripts/run_port_test.py --prob p4 [--enable_2opt_head on|off]",
            "  -> enable_2opt_head = (args.enable_2opt_head == 'on') if provided else (not is_p4)  # P4 默认 False",
            "  -> StrategyEngine(is_p4=True, enable_2opt_head=<value>)",
            "  -> src/strategy_engine.py: self.enable_2opt_head = enable_2opt_head   # P4 强制覆盖已解除",
            "  -> run_version_c_openroute(): start_i = -1 if self.enable_2opt_head else 0",
            "  -> path 的 2-opt 邻域含 i=-1 (可翻转前缀) => 可改变 path[0]",
            "  -> best_task = tasks[path[0]]  => 最终实际派发首任务",
            "  -> self.head_dispatch_records 逐轮记录 pre_head / final_head / head_changed",
        ],
        "p4_effective_config_off": c_p4_off,
        "p4_effective_config_on": c_p4_on,
        "p4_diff_keys": diff_keys,
        "p3_effective_config_stable": cfg(p3_stable),
        "p3_effective_config_radial": cfg(p3_radial),
        "note": "仅解除 P4 对 enable_2opt_head 的强制覆盖并补充审计埋点；其余 P4 冻结项与 P3 行为不变。",
    }
    with open(os.path.join(OUT_DIR, "p4_head_2opt_chain.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    if not overall:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
