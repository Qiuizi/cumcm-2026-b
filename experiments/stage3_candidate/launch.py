"""
launch.py —— 候选版启动入口（默认 stable）

用法
--------------------------------------------------
    # 默认：稳定基线
    python experiments/stage3_candidate/launch.py --version stable --case 9001:10

    # 历史接收模型候选版
    python experiments/stage3_candidate/launch.py --version history_candidate --case 9001:10

    # 多个案例
    python experiments/stage3_candidate/launch.py --version history_candidate \
        --case 9001:10 --case 9013:13 --json results/one_run.json

行为
--------------------------------------------------
  * 只使用本地参考环境 src/sim_env.py；**不调用官方模拟器，也不另建模拟器**
  * 打印"实际生效配置 + 模块来源 + 源码标识（sha256）"
  * 逐频道结束证据、计费闭合核对、现实耗时一并输出，可选写入 JSON

版本语义
--------------------------------------------------
  stable            : 冻结决策器（local_decision_frozen.LocalDecisionMaker），引擎自建，不做替换
  history_candidate : HistoryCandidateDecision + HistoryReceptionPredictor
                      （决策主体与冻结版逐字相同，仅接收概率来自历史假设集）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import conservative_grid_frozen  # noqa: E402
import local_decision_frozen  # noqa: E402
import src.evidence_tracker as ev  # noqa: E402
import src.sim_env as sim_env_mod  # noqa: E402
import src.strategy_engine as engine_mod  # noqa: E402
from candidate_decision import HistoryCandidateDecision  # noqa: E402
from observer import RecordingObserverDriver  # noqa: E402
from predictor import HistoryReceptionPredictor  # noqa: E402
from src.sim_env import SimEnvironment, LocalSimDriver  # noqa: E402
from src.strategy_engine import StrategyEngine  # noqa: E402

STABLE = "stable"
HISTORY = "history_candidate"


def sha256_file(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return "<unavailable>"


def module_source(mod) -> str:
    return getattr(mod, "__file__", "<unknown>") or "<unknown>"


def module_table() -> dict:
    return {
        "env_sim": {"module": module_source(sim_env_mod), "sha256": sha256_file(module_source(sim_env_mod))},
        "strategy_engine": {"module": module_source(engine_mod), "sha256": sha256_file(module_source(engine_mod))},
        "evidence_tracker": {"module": module_source(ev), "sha256": sha256_file(module_source(ev))},
        "decision_maker_frozen": {"module": module_source(local_decision_frozen),
                                  "sha256": sha256_file(module_source(local_decision_frozen))},
        "grid_frozen": {"module": module_source(conservative_grid_frozen),
                        "sha256": sha256_file(module_source(conservative_grid_frozen))},
        "candidate_decision": {"module": os.path.join(HERE, "candidate_decision.py"),
                               "sha256": sha256_file(os.path.join(HERE, "candidate_decision.py"))},
        "candidate_predictor": {"module": os.path.join(HERE, "predictor.py"),
                                "sha256": sha256_file(os.path.join(HERE, "predictor.py"))},
        "candidate_model": {"module": os.path.join(HERE, "model.py"),
                            "sha256": sha256_file(os.path.join(HERE, "model.py"))},
    }


def build_engine(version: str, seed: int, n_src: int, is_p4: bool = True,
                 record_updates: bool = True):
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=is_p4, seed=seed)
    drv = RecordingObserverDriver(LocalSimDriver(env))
    eng = StrategyEngine(driver=drv, is_p4=is_p4, version="C", verbose=False)
    drv.attach_engine(eng)

    dec = None
    pred = None
    if version == STABLE:
        # 引擎自建的冻结决策器原样使用；不做任何替换
        dec = eng.local_decision
    elif version == HISTORY:
        pred = HistoryReceptionPredictor(observer=drv, record_updates=record_updates)
        dec = HistoryCandidateDecision(predictor=pred, max_followups=12,
                                       max_followup_time_s=600.0, margin_s=5.0)
        eng.local_decision = dec
    else:
        raise SystemExit(f"未知版本: {version}（可选 {STABLE} / {HISTORY}）")
    return env, eng, drv, dec, pred


def effective_config(version: str, eng, dec, pred) -> dict:
    return {
        "version": version,
        "is_p4": eng.is_p4,
        "engine_version_tag": eng.version,
        "scan_at_clearance": eng.scan_at_clearance,
        "enable_2opt_head": eng.enable_2opt_head,
        "enable_adaptive_radial_coverage": eng.enable_adaptive_radial_coverage,
        "enable_pruning": eng.enable_pruning,
        "max_repeat_clear_fail": eng.max_repeat_clear_fail,
        "decision_maker": f"{type(dec).__module__}.{type(dec).__name__}",
        "decision_maker_limits": {
            "max_followups": getattr(dec, "max_followups", None),
            "max_followup_time_s": getattr(dec, "max_followup_time_s", None),
            "margin_s": getattr(dec, "margin_s", None),
        },
        "grid_class": f"{eng.grid_class.__module__}.{eng.grid_class.__name__}",
        "evidence_tracker": f"{type(eng.evidence_tracker).__module__}."
                            f"{type(eng.evidence_tracker).__name__}",
        "predictor": (pred.describe() if pred is not None else None),
    }


def run_case(version: str, seed: int, n_src: int, is_p4: bool = True) -> dict:
    env, eng, drv, dec, pred = build_engine(version, seed, n_src, is_p4=is_p4)
    t0 = time.time()
    res = eng.execute()
    real_s = time.time() - t0

    T = env.virtual_time_s
    L = env.total_distance_m
    M = env.measure_count
    S = env.switch_count
    F = env.clear_fail_count
    N = env.clear_succ_count
    closure = L / 5.0 + 5.0 * M + 1.0 * S + 3.0 * F + 5.0 * N

    out = {
        "version": version, "seed": seed, "n_src": n_src, "is_p4": is_p4,
        "T_virtual_s": round(T, 3), "L_dist_m": round(L, 2),
        "M_measures": M, "S_switches": S, "F_clear_fail": F, "N_clear_succ": N,
        "closure_s": round(closure, 3), "closure_residual_s": round(T - closure, 6),
        "closure_ok": abs(T - closure) < 1e-3,
        "cleared": res["cleared_count"], "absent": res["absent_count"],
        "unsolved": res["unsolved_count"], "failed": res["failed_count"],
        "completion_status": res["completion_status"],
        "completed_successfully": res["completed_successfully"],
        "terminal_reason": res["terminal_reason"],
        "real_time_s": round(real_s, 3),
        "per_channel_end_evidence": {
            str(ch): {"status": st.status, "absence_proof_type": st.absence_proof_type}
            for ch, st in eng.channels.items()},
        "effective_config": effective_config(version, eng, dec, pred),
        "module_sources": module_table(),
        "no_signal_census": drv.no_signal_census(),
        "action_trace": [
            {"kind": r["kind"],
             "pos": (list(r["pos"]) if r.get("pos") is not None else None),
             "channel": r.get("channel"),
             "result": r.get("result"), "t": r.get("t")}
            for r in drv.records if r["kind"] in ("measure", "clear")
        ],
    }

    if version == HISTORY:
        a = dec.audit()
        out.update({
            "model_decisions_used": a["decision_with_model_count"],
            "model_decision_fallbacks": a["decision_fallback_count"],
            "model_call_fallbacks": a["call_fallback_count"],
            "model_score_count": a["model_score_count"],
            "fallback_reason_hist": a["fallback_reason_hist"],
            "action_changed_count": a["action_changed_count"],
            "position_changed_count": a["position_changed_count"],
        })
    return out


def parse_case(s: str):
    if ":" in s:
        seed, n = s.split(":", 1)
        return int(seed), int(n)
    return int(s), 10


def main():
    ap = argparse.ArgumentParser(description="P4 候选版启动入口（本地参考环境）")
    ap.add_argument("--version", default=STABLE, choices=[STABLE, HISTORY])
    ap.add_argument("--case", action="append", default=None,
                    help="seed:源数，可重复；缺省 9001:10")
    ap.add_argument("--json", default=None, help="把逐局结果写入该 JSON")
    ap.add_argument("--p3", action="store_true", help="以 P3 方式运行（仅用于冒烟，非本阶段候选范围）")
    args = ap.parse_args()

    cases = [parse_case(s) for s in (args.case or ["9001:10"])]
    is_p4 = not args.p3

    print("=" * 100)
    print(f"P4 候选版启动入口    version = {args.version}    （默认 stable）")
    print("=" * 100)
    mt = module_table()
    print("模块来源与源码标识：")
    for k, v in mt.items():
        print(f"  {k:<22} {v['sha256'][:16]}  {v['module']}")

    records = []
    for seed, n_src in cases:
        rec = run_case(args.version, seed, n_src, is_p4=is_p4)
        records.append(rec)
        cfg = rec["effective_config"]
        print("\n" + "-" * 100)
        print(f"案例 seed={seed} 源数={n_src}  version={args.version}")
        print("-" * 100)
        print("实际生效配置：")
        for k in ("is_p4", "engine_version_tag", "scan_at_clearance", "enable_2opt_head",
                  "enable_adaptive_radial_coverage", "enable_pruning",
                  "max_repeat_clear_fail", "decision_maker", "grid_class",
                  "evidence_tracker"):
            print(f"  {k:<32} = {cfg[k]}")
        print(f"  {'decision_maker_limits':<32} = {cfg['decision_maker_limits']}")
        if cfg["predictor"]:
            p = cfg["predictor"]
            print(f"  {'predictor':<32} = {p['predictor_class']} @ {p['predictor_module']}")
            print(f"  {'  frozen_prior':<32} = {p['frozen_prior']}")
            print(f"  {'  update_rule':<32} = {p['update_rule']}")
            print(f"  {'  fallback_rule':<32} = {p['fallback_rule']}")
        print("结果：")
        print(f"  T = {rec['T_virtual_s']:.2f} s   L = {rec['L_dist_m']:.1f} m   "
              f"M = {rec['M_measures']}  S = {rec['S_switches']}  "
              f"F = {rec['F_clear_fail']}  N = {rec['N_clear_succ']}")
        print(f"  计费闭合 T-(L/5+5M+S+3F+5N) = {rec['closure_residual_s']:.6f} s  "
              f"闭合 = {rec['closure_ok']}")
        print(f"  完成 = {rec['completed_successfully']}  状态 = {rec['completion_status']}  "
              f"清除 = {rec['cleared']}/{n_src}  空频道 = {rec['absent']}  "
              f"未决 = {rec['unsolved']}  失败 = {rec['failed']}")
        print(f"  现实耗时 = {rec['real_time_s']:.2f} s")
        c = rec["no_signal_census"]
        print(f"  no_signal：总 {c['no_signal_total']}，发现后补测 {c['no_signal_followup']}，"
              f"网格存在 {c['no_signal_grid_exists']}，其中未收缩 {c['no_signal_grid_not_shrunk']}、"
              f"收缩 {c['no_signal_grid_shrunk']}")
        if args.version == HISTORY:
            print(f"  模型：用上模型决策 {rec['model_decisions_used']}，整体回退 "
                  f"{rec['model_decision_fallbacks']}，逐调用回退 {rec['model_call_fallbacks']}，"
                  f"回退原因 {rec['fallback_reason_hist']}")
            print(f"  实际改变动作 {rec['action_changed_count']} 次，改变补测点 "
                  f"{rec['position_changed_count']} 次")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"\n结果已写入 {args.json}")


if __name__ == "__main__":
    main()
