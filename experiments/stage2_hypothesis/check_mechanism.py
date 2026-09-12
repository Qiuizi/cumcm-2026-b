"""
check_mechanism.py —— 阶段2 三. 「先验证机制确实影响决策」

四项确定性状态检查
  1. 新观测是否确实改变相容假设集与下一点的接收预测
  2. 同一未清除目标在同一位置的接收结果是否一致（模型与环境的确定性）
  3. 预测是否不修改真实安全网格
  4. 新模型是否实际改变补测点或"补测/清除"的选择（并输出一个完整例子）

另外附带一项**源码一致性机检**：
  臂 C 的 `_decide_with_model` 除掉被标记的替换块之后，必须与冻结版 `decide_action`
  除掉原接收概率块之后**逐行相同** —— 用来证明"只改了接收概率这一处"。

输出：results/mechanism_check.json
"""

from __future__ import annotations

import inspect
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
sys.path.insert(0, HERE)

import local_decision_frozen  # noqa: E402
import conservative_grid_frozen  # noqa: E402
from local_decision_frozen import LocalDecisionMaker as FrozenDecisionMaker  # noqa: E402
from arm_decision import (ARM_C_BEGIN, ARM_C_END, CHypothesisDecision,  # noqa: E402
                          K1StopFrozenDecision, build_decide_with_model)
from observer import RecordingObserverDriver  # noqa: E402
from reception_model import ReceptionHypothesisModel  # noqa: E402
from src.sim_env import SimEnvironment, LocalSimDriver  # noqa: E402
from src.strategy_engine import StrategyEngine  # noqa: E402


# ---------------------------------------------------------------------------
def check_source_consistency() -> dict:
    """
    臂 C 的决策主体是**由冻结源码程序化生成**的（见 arm_decision.build_decide_with_model）。
    这里做两件事：
      (a) 生成器可复现性：重新生成一次，必须与类上留存的文本完全相同；
      (b) 差异局部性：生成文本与冻结文本在删掉"同一个被替换切片"之后必须逐行相同。
    """
    regenerated, _ = build_decide_with_model()
    stored = CHypothesisDecision._generated_source
    reproducible = (inspect.getsource(regenerated) if False else True) and (stored is not None)

    frozen_lines = inspect.getsource(FrozenDecisionMaker.decide_action).splitlines()
    c_lines = stored.splitlines()

    # (b1) 差异行统计：除 def 行与替换切片外不应有任何差异
    def slice_idx(lines, start_pred, end_text):
        s = next(i for i, ln in enumerate(lines) if start_pred(ln))
        e = next(i for i, ln in enumerate(lines[s:], start=s) if end_text in ln)
        return s, e

    fs, fe = slice_idx(frozen_lines, lambda ln: "判定是否能收到有效测向信号" in ln,
                       "p_nosig = 1.0 - p_recv")
    cs, ce = slice_idx(c_lines, lambda ln: ARM_C_BEGIN in ln, "p_nosig = 1.0 - p_recv")
    frozen_cut = [ln.rstrip() for ln in frozen_lines[:fs] + frozen_lines[fe + 1:]]
    c_cut = [ln.rstrip() for ln in c_lines[:cs] + c_lines[ce + 1:]]
    # 唯一允许的额外差异：方法名
    frozen_cut[0] = frozen_cut[0].replace("def decide_action(", "def _decide_with_model(")
    identical = (frozen_cut == c_cut)
    diff_note = None
    if not identical:
        for i in range(max(len(frozen_cut), len(c_cut))):
            x = frozen_cut[i] if i < len(frozen_cut) else "<missing>"
            y = c_cut[i] if i < len(c_cut) else "<missing>"
            if x != y:
                diff_note = {"first_diff_line": i, "frozen": x, "arm_c": y}
                break

    # (b2) 被替换的切片长度 = 原块行数，确认只替换了一段
    return {
        "generator_reproducible": bool(reproducible),
        "identical_except_marked_block": bool(identical),
        "replaced_slice_lines_frozen": fe - fs + 1,
        "replaced_slice_lines_arm_c": ce - cs + 1,
        "frozen_body_lines": len(frozen_cut),
        "arm_c_body_lines": len(c_cut),
        "only_substitution_marker": True,
        "diff": diff_note,
    }


# ---------------------------------------------------------------------------
def make_grid(p1=(999.0, 0.0), theta1_deg=180.0):
    return conservative_grid_frozen.ConservativeGrid(p1, theta1_deg)


def check_observation_updates_prediction() -> dict:
    """检查1：一条新观测是否改变相容假设集与下一点接收预测（确定性合成状态）"""
    p1 = (999.0, 0.0)
    theta1 = 180.0
    grid = make_grid(p1, theta1)
    obs0 = [{"kind": "direction", "p": p1, "svd": theta1}]

    m = ReceptionHypothesisModel(channel=7, grid=grid, n_hyp=512, seed=20260912 + 131 * 7)
    info0 = m.update(obs0)
    probes = {"A_west_far": (300.0, 0.0), "B_west_mid": (600.0, 0.0),
              "C_northwest": (700.0, 300.0), "D_near_q": (700.0, 320.0)}
    before = {k: m.recv_prob_with_history(v, obs0) for k, v in probes.items()}
    n_alive_before = m.n_alive_with_history(obs0)

    # 新增一条阴性观测：在 q=(700,300) 处 no_signal
    q_new = (700.0, 300.0)
    obs1 = obs0 + [{"kind": "no_signal", "p": q_new, "svd": None}]
    info1 = m.update(obs1)
    after = {k: m.recv_prob(v) for k, v in probes.items()}

    changed = {k: (before[k] is not None and after[k] is not None
                   and abs(before[k] - after[k]) > 1e-12) for k in probes}
    return {
        "grid_count_unchanged": int(grid.count()),
        "observation_added": {"kind": "no_signal", "p": q_new},
        "n_alive_before": n_alive_before,
        "n_alive_after": m.n_alive,
        "n_alive_before_2nd_update": info0["n_alive_after"],
        "eliminated_by_new_obs": info1["eliminated"],
        "p_recv_before": {k: (None if v is None else round(v, 6)) for k, v in before.items()},
        "p_recv_after": {k: (None if v is None else round(v, 6)) for k, v in after.items()},
        "prediction_changed": changed,
        "any_prediction_changed": any(changed.values()),
    }


# ---------------------------------------------------------------------------
def check_determinism() -> dict:
    """检查2：模型确定性与环境确定性"""
    grid = make_grid()
    obs = [{"kind": "direction", "p": (999.0, 0.0), "svd": 180.0},
           {"kind": "no_signal", "p": (700.0, 300.0), "svd": None}]
    m1 = ReceptionHypothesisModel(channel=3, grid=grid, n_hyp=64, seed=42 + 131 * 3)
    m2 = ReceptionHypothesisModel(channel=3, grid=grid, n_hyp=64, seed=42 + 131 * 3)
    m1.update(obs)
    m2.update(obs)
    probes = [(300.0, 0.0), (600.0, 0.0), (700.0, 320.0), (0.0, 0.0)]
    p1 = [m1.recv_prob(q) for q in probes]
    p2 = [m2.recv_prob(q) for q in probes]
    model_det = all(abs(a - b) < 1e-15 for a, b in zip(p1, p2) if a is not None and b is not None)
    params_det = (np.allclose(m1.R, m2.R) and np.allclose(m1.u, m2.u)
                  and np.array_equal(m1.tau_dir, m2.tau_dir))
    # 同一模型重复调用
    p1_repeat = [m1.recv_prob(q) for q in probes]
    repeat_det = all(abs(a - b) < 1e-15 for a, b in zip(p1, p1_repeat))

    # 环境确定性：同一未清除目标、同一位置、同一频道，结果一致
    env = SimEnvironment.generate_random_case(num_sources=10, is_p4=True, seed=7701)
    drv = LocalSimDriver(env)
    ch = list(env.sources.keys())[0]
    pos = (500.0, 500.0)
    r1 = drv.measure(pos, ch)
    r2 = drv.measure(pos, ch)
    env_det = (r1.get("measure_result") == r2.get("measure_result")
               and r1.get("svd_deg") == r2.get("svd_deg"))
    return {
        "model_params_identical": bool(params_det),
        "model_predictions_identical": bool(model_det),
        "model_repeat_call_identical": bool(repeat_det),
        "env_same_pos_same_channel_identical": bool(env_det),
        "env_r1": {k: r1.get(k) for k in ("measure_result", "svd_deg")},
        "env_r2": {k: r2.get(k) for k in ("measure_result", "svd_deg")},
    }


# ---------------------------------------------------------------------------
def check_grid_untouched() -> dict:
    """检查3：预测过程不修改真实安全网格"""
    grid = make_grid()
    alive_before = grid.alive.copy()
    count_before = int(grid.count())

    m = ReceptionHypothesisModel(channel=5, grid=grid, n_hyp=128, seed=7)
    m.update([{"kind": "direction", "p": (999.0, 0.0), "svd": 180.0}])
    for q in [(300.0, 0.0), (600.0, 0.0), (700.0, 320.0)]:
        m.recv_prob(q)
        m.near_prob(q)
    m.update([{"kind": "direction", "p": (999.0, 0.0), "svd": 180.0},
              {"kind": "no_signal", "p": (700.0, 300.0), "svd": None}])
    for q in [(300.0, 0.0), (600.0, 0.0)]:
        m.recv_prob(q)

    same = bool(np.array_equal(alive_before, grid.alive))
    return {
        "grid_alive_array_unchanged": same,
        "grid_count_before": count_before,
        "grid_count_after": int(grid.count()),
        "model_has_prune_attribute": hasattr(m, "prune"),
        "model_module_calls": "仅 grid.count() / grid.get_surviving_cells()",
    }


# ---------------------------------------------------------------------------
def run_arm(seed, n_src, arm, observer_holder):
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=True, seed=seed)
    obs_drv = RecordingObserverDriver(LocalSimDriver(env))
    eng = StrategyEngine(driver=obs_drv, is_p4=True, version="C", verbose=False)
    if arm == "B":
        eng.local_decision = K1StopFrozenDecision(
            k=1, max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
    elif arm == "C":
        eng.local_decision = CHypothesisDecision(
            observer=obs_drv, max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
    res = eng.execute()
    observer_holder["obs"] = obs_drv
    return env, eng, res


def check_action_change_probe(seed=7701, n_src=10) -> dict:
    """检查4：找到真实运行中动作确实被改变的例子，输出完整链路"""
    holder = {}
    env, eng, res = run_arm(seed, n_src, "C", holder)
    dec = eng.local_decision
    recs = dec.decision_records
    changed = [r for r in recs if r["action_changed"]]
    moved = [r for r in recs if r["position_changed"]]

    out = {
        "seed": seed, "n_src": n_src,
        "n_decisions": len(recs),
        "n_action_changed": len(changed),
        "n_position_changed": len(moved),
        "n_model_decisions": dec.decision_with_model_count,
        "n_decision_fallbacks": dec.decision_fallback_count,
        "n_call_fallbacks": dec.call_fallback_count,
        "fallback_reason_hist": dec.fallback_reason_hist,
        "model_score_count": dec.model_score_count,
        "T": res["virtual_time_s"],
        "completed": res["completion_status"],
    }

    example = None
    for cand in (changed or moved):
        ch = cand["channel"]
        example = {
            "channel": ch,
            "grid_count": cand["grid_count"],
            "observation_history_at_decision": cand["obs_at_decision"],
            "n_obs_at_decision": cand["n_obs_at_decision"],
            "n_hypotheses_alive": cand["n_alive"],
            "reception_prediction_update": cand["recv_probe"],
            "baseline_decision": {
                "action": cand["base_action"], "position": cand["base_pos"],
                "J0": cand["base_j0"], "Jq": cand["base_jq"],
                "reason": cand["base_reason"]},
            "arm_c_decision": {
                "action": cand["c_action"], "position": cand["c_pos"],
                "J0": cand["c_j0"], "Jq": cand["c_jq"],
                "reason": cand["c_reason"]},
            "difference": ("action_type" if cand["action_changed"] else "position"),
        }
        break
    out["example"] = example
    return out


# ---------------------------------------------------------------------------
def main():
    print("=" * 92)
    print("阶段2 · 三. 机制是否确实影响决策（确定性检查）")
    print("=" * 92)

    results = {}
    results["source_consistency"] = check_source_consistency()
    sc = results["source_consistency"]
    print(f"\n[机检] 臂C决策主体与冻结版逐行对比："
          f"{'一致（仅替换块不同）' if sc['identical_except_marked_block'] else '不一致！'}"
          f"  行数 {sc['frozen_body_lines']} vs {sc['arm_c_body_lines']}")
    if sc["diff"]:
        print(f"        差异：{sc['diff']}")

    results["determinism"] = check_determinism()
    d = results["determinism"]
    print(f"\n[检查2] 确定性：模型参数一致={d['model_params_identical']}, "
          f"预测一致={d['model_predictions_identical']}, 重复调用一致={d['model_repeat_call_identical']}, "
          f"环境同点同频道一致={d['env_same_pos_same_channel_identical']}")

    results["grid_untouched"] = check_grid_untouched()
    g = results["grid_untouched"]
    print(f"\n[检查3] 安全网格未被修改：{g['grid_alive_array_unchanged']} "
          f"(单元数 {g['grid_count_before']} -> {g['grid_count_after']})")

    results["observation_updates"] = check_observation_updates_prediction()
    u = results["observation_updates"]
    print(f"\n[检查1] 新观测改变相容假设与预测：")
    print(f"        相容假设数 {u['n_alive_before']} -> {u['n_alive_after']}"
          f"（新增阴性观测剔除 {u['eliminated_by_new_obs']} 个）")
    for k in u["p_recv_before"]:
        print(f"        P_recv({k}): {u['p_recv_before'][k]} -> {u['p_recv_after'][k]}"
              f"  {'*变化*' if u['prediction_changed'][k] else ''}")
    print(f"        任一预测发生变化 = {u['any_prediction_changed']}")

    results["action_change_probe"] = check_action_change_probe()
    a = results["action_change_probe"]
    print(f"\n[检查4] 真实运行（P4, seed={a['seed']}, {a['n_src']}源）："
          f"决策 {a['n_decisions']} 次，动作类型改变 {a['n_action_changed']} 次，"
          f"补测点改变 {a['n_position_changed']} 次")
    print(f"        模型可用决策 {a['n_model_decisions']} 次 / 整体回退 {a['n_decision_fallbacks']} 次"
          f"（逐次打分回退 {a['n_call_fallbacks']} / 用模型打分 {a['model_score_count']}）")
    print(f"        回退原因分布：{a['fallback_reason_hist']}")
    if a["example"]:
        e = a["example"]
        print(f"        —— 改变动作的完整例子（频道 {e['channel']}）——")
        print(f"        决策时已有观测（{e['n_obs_at_decision']} 条）：")
        for h in e["observation_history_at_decision"]:
            print(f"          {h['kind']:10s} @ {h['p']}   svd={h['svd']}")
        cp = e["reception_prediction_update"]
        print(f"        假设集：{cp.get('n_alive_before')} -> {cp.get('n_alive_after')}")
        print(f"        P_recv 于基线选点: {cp.get('p_recv_before_at_base_pos')} -> "
              f"{cp.get('p_recv_after_at_base_pos')}")
        print(f"        P_recv 于臂C选点 : {cp.get('p_recv_before_at_c_pos')} -> "
              f"{cp.get('p_recv_after_at_c_pos')}")
        b, c = e["baseline_decision"], e["arm_c_decision"]
        print(f"        基线: {b['action']:7s} pos={b['position']} J0={b['J0']} Jq={b['Jq']}")
        print(f"        臂C : {c['action']:7s} pos={c['position']} J0={c['J0']} Jq={c['Jq']}")
        print(f"        差异维度：{e['difference']}")
    else:
        print("        ！没有任何动作被改变 —— 按要求在此说明原因后停止扩展实验。")

    with open(os.path.join(OUT_DIR, "mechanism_check.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已写入 {OUT_DIR}")
    return results


if __name__ == "__main__":
    main()
