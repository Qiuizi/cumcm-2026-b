"""
verify_equivalence.py —— 验证 1：新接线候选版与本轮实验 C（阶段2）一致

三项检查
--------------------------------------------------
  (1) 源码局部性：candidate_decision.decide_action 与冻结版 decide_action
      在删掉"接收概率"切片后必须**逐行相同**（并核对运行期不含 inspect/exec）。
  (2) 既有案例数值一致：把新接线的候选版跑在与阶段2 完全相同的场景上，
      与 `stage2_paired_9runs.json` 中臂 C 的记录逐项比对：
      T / L / M / S / F / N / 清除 / 空频道 / 完成状态。
  (3) 动作序列一致：把阶段2 臂 C 现场重跑一遍（确定性），与新接线候选版逐动作比对
      driver 级动作序列（kind / pos / channel / result / t）。
      若不一致，先定位第一处差异再停。
"""

from __future__ import annotations

import inspect
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STAGE2 = os.path.join(ROOT, "experiments", "stage2_hypothesis")
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, STAGE2)

from local_decision_frozen import LocalDecisionMaker as FrozenDecisionMaker  # noqa: E402

from candidate_decision import CANDIDATE_BEGIN, CANDIDATE_END, HistoryCandidateDecision  # noqa: E402
from launch import HISTORY, run_case  # noqa: E402

# 阶段2 的臂 C 实现与观察器（用于对照重跑）
from arm_decision import CHypothesisDecision  # noqa: E402
from observer import RecordingObserverDriver as Stage2Observer  # noqa: E402
from src.sim_env import SimEnvironment, LocalSimDriver  # noqa: E402
from src.strategy_engine import StrategyEngine  # noqa: E402

EXISTING_CASE = (8801, 10)          # 阶段2 预注册案例之一
STAGE2_JSON = os.path.join(STAGE2, "results", "stage2_paired_9runs.json")


def strip_block(lines, start_pred, end_text):
    s = next(i for i, ln in enumerate(lines) if start_pred(ln))
    e = next(i for i, ln in enumerate(lines[s:], start=s) if end_text in ln)
    return lines[:s] + lines[e + 1:]


def check_source_locality() -> dict:
    frozen = inspect.getsource(FrozenDecisionMaker.decide_action).splitlines()
    cand = inspect.getsource(HistoryCandidateDecision._decide_with_history).splitlines()
    frozen_cut = [ln.rstrip() for ln in strip_block(
        frozen, lambda ln: "判定是否能收到有效测向信号" in ln, "p_nosig = 1.0 - p_recv")]
    cand_cut = [ln.rstrip() for ln in strip_block(
        cand, lambda ln: CANDIDATE_BEGIN in ln, "p_nosig = 1.0 - p_recv")]
    # 唯一允许的额外差异：方法名（生成主体叫 _decide_with_history，由手写 decide_action 包装）
    frozen_cut[0] = frozen_cut[0].replace("def decide_action(", "def _decide_with_history(")
    identical = frozen_cut == cand_cut
    diff = None
    if not identical:
        for i in range(max(len(frozen_cut), len(cand_cut))):
            x = frozen_cut[i] if i < len(frozen_cut) else "<missing>"
            y = cand_cut[i] if i < len(cand_cut) else "<missing>"
            if x != y:
                diff = {"line": i, "frozen": x, "candidate": y}
                break

    with open(os.path.join(HERE, "candidate_decision.py"), encoding="utf-8") as f:
        src = f.read()
    return {
        "identical_except_prediction_block": identical,
        "frozen_lines": len(frozen_cut),
        "candidate_lines": len(cand_cut),
        "first_diff": diff,
        "runtime_uses_inspect_or_exec": ("inspect" in src) or ("exec(" in src),
    }


def stage2_arm_c_trace(seed, n_src):
    """现场重跑阶段2 臂 C，返回 (记录, 动作序列)"""
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
    drv = Stage2Observer(LocalSimDriver(env))
    eng = StrategyEngine(driver=drv, is_p4=True, version="C", verbose=False)
    eng.local_decision = CHypothesisDecision(observer=drv, max_followups=12,
                                             max_followup_time_s=600.0, margin_s=5.0)
    res = eng.execute()
    trace = [{"kind": r["kind"], "pos": list(r.get("pos", []) or []),
              "channel": r.get("channel"), "result": r.get("result"),
              "t": r.get("t")} for r in drv.records if r["kind"] in ("measure", "clear")]
    return {
        "T_virtual_s": round(env.virtual_time_s, 3),
        "L_dist_m": round(env.total_distance_m, 2),
        "M_measures": env.measure_count, "S_switches": env.switch_count,
        "F_clear_fail": env.clear_fail_count, "N_clear_succ": env.clear_succ_count,
        "cleared": res["cleared_count"], "absent": res["absent_count"],
        "completion_status": res["completion_status"],
    }, trace


def main():
    print("=" * 100)
    print("验证 1：新接线候选版 vs 阶段2 实验 C（既有案例）")
    print("=" * 100)

    results = {}

    # (1) 源码局部性
    loc = check_source_locality()
    results["source_locality"] = loc
    print(f"\n[1] 源码局部性：{'一致（仅接收概率切片不同）' if loc['identical_except_prediction_block'] else '不一致！'}"
          f"  行数 {loc['frozen_lines']} vs {loc['candidate_lines']}")
    print(f"    运行期是否使用 inspect/exec = {loc['runtime_uses_inspect_or_exec']}")
    if loc["first_diff"]:
        print(f"    第一处差异：{loc['first_diff']}")

    # (2) 与阶段2 持久化记录比对
    with open(STAGE2_JSON, encoding="utf-8") as f:
        s2 = json.load(f)
    ref = next(r for r in s2["records"]
               if r["arm"] == "C" and r["seed"] == EXISTING_CASE[0]
               and r["n_src"] == EXISTING_CASE[1])
    new = run_case(HISTORY, EXISTING_CASE[0], EXISTING_CASE[1])
    keys = ["T_virtual_s", "L_dist_m", "M_measures", "S_switches", "F_clear_fail",
            "N_clear_succ", "cleared", "absent", "completion_status"]
    cmp_num = {k: {"stage2_C": ref[k], "candidate": new[k],
                   "equal": ref[k] == new[k]} for k in keys}
    results["numeric_vs_stage2C"] = {"case": EXISTING_CASE, "fields": cmp_num,
                                     "all_equal": all(v["equal"] for v in cmp_num.values())}
    print(f"\n[2] 既有案例 {EXISTING_CASE[0]}:{EXISTING_CASE[1]} 与阶段2 臂 C 记录比对：")
    for k in keys:
        v = cmp_num[k]
        print(f"    {k:<20} stage2C={v['stage2_C']!s:<14} candidate={v['candidate']!s:<14} "
              f"{'OK' if v['equal'] else 'DIFF'}")
    print(f"    全部一致 = {results['numeric_vs_stage2C']['all_equal']}")

    # (3) 动作序列逐动作比对（pos 统一归一化为 list，避免 tuple/list 类型差异误报）
    ref_rec, ref_trace = stage2_arm_c_trace(*EXISTING_CASE)
    cand_trace = new["action_trace"]

    def norm(tr):
        return [{**r, "pos": (list(r["pos"]) if r.get("pos") is not None else None)}
                for r in tr]

    ref_trace, cand_trace = norm(ref_trace), norm(cand_trace)
    n = min(len(ref_trace), len(cand_trace))
    first_diff = None
    for i in range(n):
        if ref_trace[i] != cand_trace[i]:
            first_diff = {"index": i, "stage2": ref_trace[i], "candidate": cand_trace[i]}
            break
    same_len = len(ref_trace) == len(cand_trace)
    seq_equal = same_len and first_diff is None
    results["action_sequence"] = {
        "case": EXISTING_CASE,
        "n_actions_stage2": len(ref_trace), "n_actions_candidate": len(cand_trace),
        "same_length": same_len, "first_diff": first_diff, "identical": seq_equal,
        "stage2_rerun_T": ref_rec["T_virtual_s"], "candidate_T": new["T_virtual_s"],
    }
    print(f"\n[3] driver 级动作序列比对：")
    print(f"    动作数 stage2C={len(ref_trace)}  candidate={len(cand_trace)}  "
          f"长度相同={same_len}")
    print(f"    逐动作完全一致 = {seq_equal}")
    if first_diff:
        print(f"    第一处差异 @ {first_diff['index']}:")
        print(f"      stage2C  : {first_diff['stage2']}")
        print(f"      candidate: {first_diff['candidate']}")
    print(f"    重跑 T: stage2C={ref_rec['T_virtual_s']:.3f}  "
          f"candidate={new['T_virtual_s']:.3f}")

    all_pass = (loc["identical_except_prediction_block"]
                and not loc["runtime_uses_inspect_or_exec"]
                and results["numeric_vs_stage2C"]["all_equal"]
                and seq_equal)
    results["all_pass"] = bool(all_pass)
    print(f"\n验证 1 总体结论：{'PASS' if all_pass else 'FAIL'}")
    if not all_pass:
        print("  按要求：先定位差异，不进入独立验证。")

    with open(os.path.join(OUT_DIR, "verify_equivalence.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"结果已写入 {os.path.join(OUT_DIR, 'verify_equivalence.json')}")
    return all_pass


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
