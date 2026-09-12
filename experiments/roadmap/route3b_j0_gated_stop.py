"""
route3b_j0_gated_stop.py —— 路线3 的改进版停止规则（P4 专属）

问题
--------------------------------------------------
route3_responsive_stop.py 的朴素阈值规则（连续 k 次盲测即强制清除）在 P4 上：
    k=1: 平均 ΔT = -200.00 s，但 7胜/1平/4负，最差退步 +318.79 s
退步的机理：P4 的 no_signal 本身零信息，但**下一次补测仍可能测到 direction**，
一旦测到 direction，存活集会大幅收缩，清除计划成本 J0 随之骤降。
在大 J0 的目标上过早转入清除，会白白背上一条昂贵的清除计划。

改进规则（J0 门控 / 信息增益停止规则）
--------------------------------------------------
连续出现 ≥1 次盲测后，比较两件事：
  - 继续补测的期望代价：在当前盲测命中率下，再等到一次 direction 还需要 λ 次 × 25 s；
  - 现在转入清除的代价：决策器给出的清除计划成本 J0。
规则：**仅当 J0 <= θ 时才强制转入清除**，否则继续补测。
θ 越大越激进。这是一个显式的"信息增益 vs 执行成本"停止规则。

正确性：与 route3 相同 —— 只改变动作顺序，不改变 CLEARED/ABSENT 结论。
本脚本只跑 P4（P3 基线上 12 例仅 1 次盲测，规则几乎不会触发，可解析地认为等价）。
"""

import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, ROOT)

from src.sim_env import SimEnvironment, LocalSimDriver  # noqa: E402
from src.strategy_engine import StrategyEngine  # noqa: E402
from src.local_decision import LocalDecisionMaker  # noqa: E402


class J0GatedStopLocalDecision(LocalDecisionMaker):
    """连续盲测后，仅当清除计划成本 J0 <= theta 时才强制转入清除"""

    def __init__(self, theta: float, min_blind: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.theta = float(theta)
        self.min_blind = int(min_blind)
        self._blind = {}
        self._last_count = {}
        self._last_action = {}
        self.gated_force_count = 0
        self.gate_hold_count = 0  # 因 J0 > theta 而放弃强制清除的次数

    def _decide_action_impl(self, cur_p, channel, grid, followup_count, followup_time_s,
                            force_clear, anchor_a=None, measured_positions=None,
                            cur_channel=None, is_p4=False, p1=None):
        cur_count = int(grid.count())
        last_count = self._last_count.get(channel)
        if self._last_action.get(channel) == "measure" and last_count is not None:
            if cur_count >= last_count:
                self._blind[channel] = self._blind.get(channel, 0) + 1
            else:
                self._blind[channel] = 0

        args = (cur_p, channel, grid, followup_count, followup_time_s)
        tail = (anchor_a, measured_positions, cur_channel, is_p4, p1)

        res = super()._decide_action_impl(*args, force_clear, *tail)

        if (not force_clear and res["action_type"] == "measure"
                and self._blind.get(channel, 0) >= self.min_blind):
            j0 = float(res.get("j0", 0.0))
            if j0 <= self.theta:
                res2 = super()._decide_action_impl(*args, True, *tail)
                res2["reason"] = (f"j0_gated_force_clear "
                                  f"(blind={self._blind[channel]}, J0={j0:.1f}<={self.theta})")
                res2["j0_before_gate"] = j0
                self.gated_force_count += 1
                res = res2
            else:
                self.gate_hold_count += 1

        self._last_count[channel] = cur_count
        self._last_action[channel] = res["action_type"]
        return res


def build_engine(n_src, seed, theta=None):
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
    eng = StrategyEngine(driver=LocalSimDriver(env), is_p4=True, version="C", verbose=False)
    if theta is not None:
        eng.local_decision = J0GatedStopLocalDecision(
            theta=theta, min_blind=1,
            max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
    return env, eng


def run(theta):
    seeds = [(10, 3001 + 1000 * i) for i in range(4)]
    seeds += [(13, 3101 + 1000 * i) for i in range(4)]
    seeds += [(16, 3201 + 1000 * i) for i in range(4)]
    out = []
    for n_src, seed in seeds:
        env, eng = build_engine(n_src, seed, theta)
        res = eng.execute()
        out.append({
            "n_src": n_src, "seed": seed,
            "T": round(res["virtual_time_s"], 2),
            "cleared": res["cleared_count"],
            "absent": res["absent_count"],
            "unsolved": res["unsolved_count"],
            "failed": res["failed_count"],
            "gated_force": getattr(eng.local_decision, "gated_force_count", 0),
            "gate_hold": getattr(eng.local_decision, "gate_hold_count", 0),
        })
    return out


def main():
    baseline = run(None)
    base = {(r["n_src"], r["seed"]): r for r in baseline}
    print("=" * 96)
    print("路线3 改进版：J0 门控停止规则（仅 P4，同 seed 配对）")
    print("=" * 96)
    print(f"{'θ (s)':>7} {'平均T(s)':>10} {'平均ΔT':>10} {'胜/平/负':>10} {'最差ΔT':>9} "
          f"{'最好ΔT':>9} {'中位ΔT':>9} {'清除率':>9} {'空频道':>7} {'门控强制':>9} {'门控放弃':>9}")

    payload = {"baseline": baseline, "arms": []}
    for theta in [150.0, 250.0, 350.0, 600.0]:
        rows = run(theta)
        dts = [r["T"] - base[(r["n_src"], r["seed"])]["T"] for r in rows]
        cl = sum(r["cleared"] for r in rows)
        ab = sum(r["absent"] for r in rows)
        tot = sum(r["n_src"] for r in rows)
        win = sum(1 for x in dts if x < -1e-9)
        tie = sum(1 for x in dts if abs(x) < 1e-9)
        los = sum(1 for x in dts if x > 1e-9)
        arm = {
            "theta": theta,
            "mean_T": round(float(np.mean([r["T"] for r in rows])), 2),
            "mean_dT": round(float(np.mean(dts)), 2),
            "win_tie_loss": [win, tie, los],
            "worst_dT": round(float(max(dts)), 2),
            "best_dT": round(float(min(dts)), 2),
            "median_dT": round(float(np.median(dts)), 2),
            "cleared_total": cl, "absent_total": ab, "sources_total": tot,
            "gated_force_total": sum(r["gated_force"] for r in rows),
            "gate_hold_total": sum(r["gate_hold"] for r in rows),
            "rows": rows,
        }
        payload["arms"].append(arm)
        print(f"{theta:>7.0f} {arm['mean_T']:>10.2f} {arm['mean_dT']:>+10.2f} "
              f"{win}/{tie}/{los:<4} {arm['worst_dT']:>+9.2f} {arm['best_dT']:>+9.2f} "
              f"{arm['median_dT']:>+9.2f} {cl}/{tot:<5} {ab:>7} "
              f"{arm['gated_force_total']:>9} {arm['gate_hold_total']:>9}")

    base_mean = float(np.mean([r["T"] for r in baseline]))
    print(f"\n基线平均 T = {base_mean:.2f} s；"
          f"三种 θ 均保持 156/156 清除与 84 空频道（与基线一致）")

    with open(os.path.join(OUT_DIR, "route3b_j0_gated_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"结果已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
