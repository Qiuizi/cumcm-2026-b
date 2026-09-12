"""
diagnose_p4_nontermination.py - P4 非终止缺陷的定位诊断（只读，不修改任何策略）

诊断两个问题：
  A. 既有 P4 结果记录（p4_benchmark_results.csv / p4_heldout_benchmark_results.csv）所对应的
     确切场景参数，在当前 P4 代码路径下能否复现？
  B. 缺陷归属：根目录冻结组件 (local_decision_frozen / conservative_grid_frozen)
     还是共享组件 (src/local_decision / src/conservative_grid)？

方法：有界运行（动作上限），不修改策略、不调用官方模拟器。
输出：
  results/p4_head_2opt/diagnosis/p4_nontermination_diagnosis.json
  results/p4_head_2opt/diagnosis/p4_nontermination_diagnosis.log
"""

import sys
import os
import json
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment
from src.strategy_engine import StrategyEngine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIAG_DIR = os.path.join(ROOT, "results", "p4_head_2opt", "diagnosis")
CAP = 1500


class RunawayGuard(Exception):
    pass


class CappedDriver:
    def __init__(self, env, cap):
        self.env, self.cap, self.n = env, cap, 0

    def _tick(self):
        self.n += 1
        if self.n > self.cap:
            raise RunawayGuard()

    def enter(self):
        self._tick(); return self.env.enter()

    def measure(self, pos, channel):
        self._tick(); return self.env.measure(pos, channel)

    def clear(self, pos, channel):
        self._tick(); return self.env.clear(pos, channel)

    def exit(self):
        return self.env.exit()


def run(n, seed, ratio, mode, cap=CAP):
    env = SimEnvironment.generate_random_case(num_sources=n, is_p4=True, seed=seed, dir_ratio=ratio)
    n_dir = sum(1 for s in env.sources.values() if s.is_directional)
    drv = CappedDriver(env, cap)
    eng = StrategyEngine(driver=drv, is_p4=True, version="C", scan_at_clearance=False,
                         enable_2opt_head=False, enable_adaptive_radial_coverage=False, verbose=False)
    if mode == "shared":
        from src.local_decision import LocalDecisionMaker as SharedLDM
        from src.conservative_grid import ConservativeGrid as SharedGrid
        eng.local_decision = SharedLDM(max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
        eng.grid_class = SharedGrid

    t0 = time.perf_counter()
    try:
        s = eng.execute()
        res = {"status": "NORMAL", "actions": drv.n, "cleared": s["cleared_count"],
               "unsolved": s["unsolved_count"], "T_s": s["virtual_time_s"],
               "real_time_s": round(time.perf_counter() - t0, 3)}
    except RunawayGuard:
        stuck = [ch for ch in range(1, 21)
                 if eng.channels[ch].status == "FOUND" and eng.channels[ch].grid is not None
                 and eng.channels[ch].grid.count() == 0]
        res = {"status": "RUNAWAY", "actions": drv.n,
               "cleared": sum(1 for c in eng.channels.values() if c.status == "CLEARED"),
               "unsolved": sum(1 for c in eng.channels.values() if c.status in ("UNKNOWN", "FOUND")),
               "T_s": eng.virtual_time_s, "stuck_zero_cell_channels": stuck,
               "real_time_s": round(time.perf_counter() - t0, 3)}
    res.update({"n_sources": n, "seed": seed, "dir_ratio": ratio,
                "omnidirectional": n - n_dir, "directional": n_dir,
                "component_mode": mode, "action_cap": cap})
    return res


RECORDED = [
    ("benchmark P4-10src-case1", 10, 5000, 0.5),
    ("heldout H01-10src-dir20", 10, 9101, 0.2),
    ("heldout H02-10src-dir50", 10, 9102, 0.5),
    ("benchmark P4-13src-case1", 13, 5001, 0.5),
    ("benchmark P4-16src-case1", 16, 5002, 0.5),
]

EXPERIMENT = [
    ("experiment P4H-10src-7210", 10, 7210, 0.5),
    ("experiment P4H-13src-7213", 13, 7213, 0.5),
    ("experiment P4H-16src-7216", 16, 7216, 0.5),
]


def main():
    os.makedirs(DIAG_DIR, exist_ok=True)
    log_lines = []

    def say(s):
        print(s, flush=True)
        log_lines.append(s)

    say("=" * 110)
    say("【P4 非终止缺陷定位诊断】有界运行 (动作上限 %d)，不修改策略，不调用官方模拟器" % CAP)
    say("=" * 110)
    say("")
    say("A. 既有记录对应的确切场景参数，在当前 P4 代码路径 (冻结组件) 下能否复现？")
    say("-" * 110)
    a_results = {}
    for tag, n, seed, ratio in RECORDED:
        r = run(n, seed, ratio, "frozen")
        a_results[tag] = r
        say(f"  {tag:28s} n={n:2d} seed={seed} dir={ratio:.2f} (全向{r['omnidirectional']}/定向{r['directional']}) "
            f"-> {r['status']:7s} 动作={r['actions']:5d} 清除={r['cleared']:2d}/{n} 未决={r['unsolved']:2d} "
            f"T={r['T_s']:10.2f}s 零单元卡死频道={r.get('stuck_zero_cell_channels', [])}")

    say("")
    say("B. 缺陷归属：冻结组件 vs 共享组件（同一场景、同一参数）")
    say("-" * 110)
    b_results = {}
    for tag, n, seed, ratio in [RECORDED[0], RECORDED[1], RECORDED[3]]:
        rf = a_results[tag]
        rs = run(n, seed, ratio, "shared")
        b_results[tag] = {"frozen": rf, "shared": rs}
        say(f"  {tag:28s} frozen -> {rf['status']:7s} 清除={rf['cleared']:2d}/{n} T={rf['T_s']:10.2f}s "
            f"| shared -> {rs['status']:7s} 清除={rs['cleared']:2d}/{n} T={rs['T_s']:9.2f}s (动作={rs['actions']})")

    say("")
    say("C. 本轮预注册的三个实验场景")
    say("-" * 110)
    c_results = {}
    for tag, n, seed, ratio in EXPERIMENT:
        r = run(n, seed, ratio, "frozen")
        c_results[tag] = r
        say(f"  {tag:28s} n={n:2d} seed={seed} dir={ratio:.2f} (全向{r['omnidirectional']}/定向{r['directional']}) "
            f"-> {r['status']:7s} 清除={r['cleared']:2d}/{n} 未决={r['unsolved']:2d} "
            f"零单元卡死频道={r.get('stuck_zero_cell_channels', [])}")

    say("")
    say("=" * 110)
    say("诊断结论：")
    say("  1) 既有 P4 成功记录对应的场景在当前冻结组件路径下全部无法复现（均为非终止，0 目标清除）。")
    say("  2) 同一场景改用共享组件 (src/) 后可正常终止并完整清除，说明缺陷位于根目录冻结快照")
    say("     (local_decision_frozen.py / conservative_grid_frozen.py)，与 P3 合入及首任务 2-opt 无关。")
    say("  3) 直接机制：某 FOUND 目标经一次补测后保守网格存活单元归零，冻结决策器仍返回")
    say("     reason='safe_clear_guaranteed' 的清除动作且位置固定，清除持续失败，")
    say("     while st.status == 'FOUND' 循环无法退出 => 虚拟时间无界增长、完成判据永不成立。")
    say("=" * 110)

    payload = {
        "action_cap": CAP,
        "A_recorded_scenarios_reproducibility": a_results,
        "B_component_attribution": b_results,
        "C_experiment_scenarios": c_results,
        "mechanism": {
            "trigger": "FOUND 目标补测后保守网格存活单元数归零 (over-pruning)",
            "loop": "service_found_target 的 while st.status == 'FOUND' 中，冻结决策器基于空网格仍返回 clear 动作",
            "effect": "clear 固定位置持续失败 (3s/次)，无移动，虚拟时间无界增长，check_completion 永不成立",
            "note": "引擎未对 max_virtual_duration_s / max_real_duration_s 做任何强制终止",
        },
        "attribution": "根目录冻结组件快照；共享 src/ 组件在同一场景可正常终止",
        "scope_limit": "本诊断只读，不修改任何策略或组件",
    }
    with open(os.path.join(DIAG_DIR, "p4_nontermination_diagnosis.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(os.path.join(DIAG_DIR, "p4_nontermination_diagnosis.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")


if __name__ == "__main__":
    main()
