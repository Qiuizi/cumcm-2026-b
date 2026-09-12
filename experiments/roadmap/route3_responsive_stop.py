"""
route3_responsive_stop.py —— 路线3（利用历史阴性更新接收判断）的离线可行性研究

【不修改 src/ 下任何 P3/P4 文件；不调用官方模拟器；只使用本地参考环境 src/sim_env.py】
本脚本通过 **子类注入**（不改原文件）替换本地决策器对象，观察"连续 no_signal 后提前转入清除"
的效果。P3/P4 的默认行为在未注入时完全不变。

route3 要处理的损失
--------------------------------------------------
`src/local_decision.py` 的固定停止条件：
    max_followups = 12
    max_followup_time_s = 600
只要"补测"仍被预测为划算，就会一直补测到上限。实测日志（results/audit_logs/
case1_action_history_c_openroute.txt）中出现同一目标连续 5 次 no_signal、
每次 25 s、共 125 s 完全无信息增益的空转（该案例共 3 个此类目标，约 400 s / 4962 s）。

理论要点（本脚本用数值/日志证据支撑）
--------------------------------------------------
1. 全向源（P3）：no_signal 的信息已被完全利用 —— 恰能排除 B(q,1000)（题设 R >= 1000）。
   因此"更新半径/类型假设"在**空间裁剪层**没有余量；余量只在**决策层**（何时停止补测）。
2. 未知类型/朝向（P4）：单个 no_signal 的**空间**信息为零。
   证明：设候选真位置 x，静默点 q，|q-x| <= 1000。若源在 x，只需其波束朝向 u 满足
   (q-x)·u < 0 即可同时解释"收到过方向"与"在 q 静默"；当 (q-x) 与 (p-x) 不严格同向时
   这样的 u 总存在。故不能删除 x。P4 现行实现干脆不做任何裁剪，这一点是**保守但正确**的。
   => "连续 12 次盲测" 不可能靠空间裁剪消除，只能靠**停止规则**消除。
3. 因此可行的 route3 形式是：把固定的 max_followups/max_followup_time 换成
   "后验信息增益"停止规则 —— 连续 k 次补测未使存活集收缩，则判定后续补测不再有信息
   增益，立即提交清除计划。

正确性属性（可证明，且本脚本用清除率/ABSENT 计数核验）
--------------------------------------------------
强制转入清除只改变**动作顺序**，不改变任何证据判定：
  - 全向源的 no_signal 裁剪是可靠的（R >= 1000），真值单元永不被删，清除计划仍覆盖真值；
  - P4 的 no_signal 本就不裁剪。
故 CLEARED / ABSENT 的最终结论与基线一致，差异只体现在虚拟总时间 T。
"""

import json
import os
import re
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

BLIND_RE = re.compile(r"目标 (\d+) 补测 no_signal")


# ----------------------------------------------------------------------------
# 注入式停止规则（子类，不修改 src/local_decision.py）
# ----------------------------------------------------------------------------
class ResponsiveStopLocalDecision(LocalDecisionMaker):
    """
    在"连续 k 次补测未收缩存活集"后强制转入清除。

    盲测检测只用决策器自身可见的状态：上一次决策是否为 measure、
    以及网格存活单元数是否收缩。不读取任何真值，不引入信息捷径。
    """

    def __init__(self, stop_after_blind: int, **kwargs):
        super().__init__(**kwargs)
        self.stop_after_blind = int(stop_after_blind)
        self._blind = {}
        self._last_count = {}
        self._last_action = {}
        self.blind_events = []
        self.forced_clear_count = 0

    def _decide_action_impl(self, cur_p, channel, grid, followup_count, followup_time_s,
                            force_clear, anchor_a=None, measured_positions=None,
                            cur_channel=None, is_p4=False, p1=None):
        cur_count = int(grid.count())
        last_count = self._last_count.get(channel)
        if self._last_action.get(channel) == "measure" and last_count is not None:
            if cur_count >= last_count:
                self._blind[channel] = self._blind.get(channel, 0) + 1
                self.blind_events.append({
                    "channel": channel,
                    "blind_run_len": self._blind[channel],
                    "followup_count": followup_count,
                    "cells": cur_count,
                })
            else:
                self._blind[channel] = 0

        if self._blind.get(channel, 0) >= self.stop_after_blind and not force_clear:
            self.forced_clear_count += 1
            res = super()._decide_action_impl(
                cur_p, channel, grid, followup_count, followup_time_s, True,
                anchor_a, measured_positions, cur_channel, is_p4, p1)
            res["reason"] = f"responsive_stop_forced_clear (blind={self._blind[channel]})"
            res["responsive_stop_triggered"] = True
            self._last_count[channel] = cur_count
            self._last_action[channel] = res["action_type"]
            return res

        res = super()._decide_action_impl(
            cur_p, channel, grid, followup_count, followup_time_s, force_clear,
            anchor_a, measured_positions, cur_channel, is_p4, p1)
        self._last_count[channel] = cur_count
        self._last_action[channel] = res["action_type"]
        return res


def build_engine(n_src, seed, is_p4, stop_after_blind=None):
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=is_p4, seed=seed)
    drv = LocalSimDriver(env)
    eng = StrategyEngine(driver=drv, is_p4=is_p4, version="C", verbose=False)
    if stop_after_blind is not None:
        eng.local_decision = ResponsiveStopLocalDecision(
            stop_after_blind=stop_after_blind,
            max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
    return env, eng


# ----------------------------------------------------------------------------
# 基线盲测链统计（直接从 log_history 解析，无需注入）
# ----------------------------------------------------------------------------
def blind_chain_stats(eng, log_history):
    """按频道切分 log_history，统计连续 no_signal 链"""
    per_channel = {}
    for line in log_history:
        m = BLIND_RE.search(line)
        if not m:
            continue
        t = float(line[1:line.index("s]")])
        ch = int(m.group(1))
        per_channel.setdefault(ch, []).append(t)

    chains = []
    for ch, times in per_channel.items():
        times_sorted = sorted(times)
        run = [times_sorted[0]]
        for prev, cur in zip(times_sorted, times_sorted[1:]):
            if abs(cur - prev) <= 30.0 + 1e-6:  # 单步补测耗时约 25s，允许余量
                run.append(cur)
            else:
                chains.append((ch, run))
                run = [cur]
        chains.append((ch, run))

    total_blind = sum(len(r) for _, r in chains)
    max_run = max((len(r) for _, r in chains), default=0)
    # 时间损失：链内相邻两次盲测的间隔之和（= 继续盲测所付出的时间）
    waste_beyond_first = 0.0
    waste_all = 0.0
    detail = []
    for ch, run in chains:
        spans = [cur - prev for prev, cur in zip(run, run[1:])]
        if run:
            waste_all += sum(spans) + 25.0
        waste_beyond_first += sum(spans)
        detail.append({
            "channel": ch,
            "run_len": len(run),
            "span_total_s": round(sum(spans), 2),
            "start_s": round(run[0], 2),
        })
    return {
        "n_blind_measures": int(total_blind),
        "n_chains": len(chains),
        "max_run_len": int(max_run),
        "chains": sorted(detail, key=lambda d: -d["run_len"]),
        "waste_beyond_first_s": round(waste_beyond_first, 2),
    }


def run_once(n_src, seed, is_p4, stop_after_blind=None):
    env, eng = build_engine(n_src, seed, is_p4, stop_after_blind)
    res = eng.execute()
    stats = blind_chain_stats(eng, eng.log_history)
    out = {
        "n_src": n_src,
        "seed": seed,
        "is_p4": is_p4,
        "stop_after_blind": stop_after_blind,
        "cleared": res["cleared_count"],
        "absent": res["absent_count"],
        "unsolved": res["unsolved_count"],
        "failed": res["failed_count"],
        "T": round(res["virtual_time_s"], 2),
        "dist_m": round(env.total_distance_m, 1),
        "measures": env.measure_count,
        "switches": env.switch_count,
        "clear_succ": env.clear_succ_count,
        "clear_fail": env.clear_fail_count,
        "completion_status": res["completion_status"],
        "blind": stats,
    }
    if stop_after_blind is not None:
        out["forced_clear_count"] = getattr(eng.local_decision, "forced_clear_count", 0)
    return out


def main():
    seeds = [(10, 3001 + 1000 * i) for i in range(4)]
    seeds += [(13, 3101 + 1000 * i) for i in range(4)]
    seeds += [(16, 3201 + 1000 * i) for i in range(4)]

    payload = {"baseline": [], "variants": [], "summary": {}}

    print("=" * 84)
    print("路线3：利用历史阴性更新接收判断 —— 连续 no_signal 后的提前停止规则")
    print("=" * 84)
    print("基线（src/local_decision.py 固定 max_followups=12 / max_followup_time_s=600）")
    print(f"{'问题':<5} {'源数':>4} {'seed':>6} {'清除':>5} {'空频道':>6} {'T(s)':>9} "
          f"{'盲测次数':>8} {'最长盲测链':>10} {'盲测链时间(s)':>13}")

    for is_p4 in [False, True]:
        for n_src, seed in seeds:
            r = run_once(n_src, seed, is_p4)
            payload["baseline"].append(r)
            tag = "P4" if is_p4 else "P3"
            print(f"{tag:<5} {n_src:>4} {seed:>6} {r['cleared']:>5} {r['absent']:>6} "
                  f"{r['T']:>9.2f} {r['blind']['n_blind_measures']:>8} "
                  f"{r['blind']['max_run_len']:>10} {r['blind']['waste_beyond_first_s']:>13.1f}")

    print("\n变异：连续 k 次盲测后强制转入清除（同一 seed 配对）")
    print(f"{'k':>3} {'问题':<5} {'清除率':>8} {'空频道':>6} {'平均T(s)':>10} {'相对基线ΔT':>11} "
          f"{'平均盲测次数':>11} {'强制清除次数':>11}")

    for k in [1, 2, 3]:
        summary = {}
        for is_p4 in [False, True]:
            tag = "P4" if is_p4 else "P3"
            base = [r for r in payload["baseline"] if r["is_p4"] == is_p4]
            tot_src = sum(r["n_src"] for r in base)
            base_T = float(np.mean([r["T"] for r in base]))
            cleared = 0
            absent = 0
            Ts = []
            blinds = []
            forced = []
            for n_src, seed in seeds:
                r = run_once(n_src, seed, is_p4, stop_after_blind=k)
                payload["variants"].append(r)
                cleared += r["cleared"]
                absent += r["absent"]
                Ts.append(r["T"])
                blinds.append(r["blind"]["n_blind_measures"])
                forced.append(r["forced_clear_count"])
            summary[tag] = {
                "k": k,
                "cleared_total": cleared,
                "total_sources": tot_src,
                "absent_total": absent,
                "mean_T": round(float(np.mean(Ts)), 2),
                "mean_dT_vs_baseline": round(float(np.mean(Ts)) - base_T, 2),
                "mean_blind_measures": round(float(np.mean(blinds)), 2),
                "mean_forced_clear": round(float(np.mean(forced)), 2),
            }
            s = summary[tag]
            print(f"{k:>3} {tag:<5} {cleared}/{tot_src:<4} {absent:>6} {s['mean_T']:>10.2f} "
                  f"{s['mean_dT_vs_baseline']:>+11.2f} {s['mean_blind_measures']:>11.2f} "
                  f"{s['mean_forced_clear']:>11.2f}")
        payload["summary"][f"k{k}"] = summary

    with open(os.path.join(OUT_DIR, "route3_responsive_stop_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    # 盲测链明细
    worst = sorted(payload["baseline"], key=lambda r: -r["blind"]["max_run_len"])[:5]
    print("\n盲测最长的 5 个基线案例：")
    for r in worst:
        tag = "P4" if r["is_p4"] else "P3"
        chains = r["blind"]["chains"][:4]
        print(f"  {tag} {r['n_src']}源 seed={r['seed']}: 最长链 "
              f"{r['blind']['max_run_len']} 次, 盲测总次数 {r['blind']['n_blind_measures']}, "
              f"链耗时 {r['blind']['waste_beyond_first_s']:.0f}s, T={r['T']:.0f}s")
        for c in chains:
            print(f"      频道 {c['channel']:>2}: 连续 {c['run_len']} 次, 跨度 {c['span_total_s']}s, "
                  f"起始 {c['start_s']}s")

    print(f"\n结果已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
