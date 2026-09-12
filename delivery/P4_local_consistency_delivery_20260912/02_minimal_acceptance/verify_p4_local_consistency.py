"""
verify_p4_local_consistency.py - P4 局部预测/执行一致性四处缺陷的最小验收

仅覆盖本轮指出的四处缺陷，不扩大无关测试：
  A 预测角域反向不等号 -> 预测必须克隆真实网格并复用真实观测更新函数，删除手写角域判据；
                          预测不得修改原网格；零概率分支不参与评估
  B 假想真坐标直接规划清除 -> 删除 plan_dir=[sc] 与"走向 sc"的补偿；
                              J0/J(q) 只按算法可生成的计划累计成本；不得注入 300s/1e9 人为惩罚
  C 50 步截断 -> 计划必须覆盖全部存活单元：对每个 z 存在 q 使 ||z-q||+d_g <= 20
  D 冻结网格缺少 prune_by_near -> 补齐并验证 near 反馈可进入清除且无缺失方法异常

保留既有空集/矛盾处理；不通过"忽略异常"或"删除目标"来通过验收。
输出：results/p4_local_consistency/acceptance/minimal_acceptance.json
"""

import sys
import os
import json
import math

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import conservative_grid_frozen as cgf
import local_decision_frozen as ldf
from src.strategy_engine import StrategyEngine

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "results", "p4_local_consistency", "acceptance")


class ScriptedDriver:
    """脚本化驱动：只用于 near 反馈链的端到端最小验收"""

    def __init__(self, measure_queue, clear_success=True):
        self.measure_queue = list(measure_queue)
        self.clear_success = clear_success
        self.vt = 0.0
        self.clear_calls = []
        self.measure_calls = []

    def enter(self):
        return {"accepted": True, "virtual_time_s": 0.0, "max_virtual_duration_s": 360000.0,
                "max_real_duration_s": 1200.0, "remaining_real_duration_s": 1200}

    def measure(self, pos, channel):
        self.measure_calls.append((tuple(pos), channel))
        self.vt += 5.0
        res = self.measure_queue.pop(0) if self.measure_queue else {"measure_result": "no_signal"}
        out = {"accepted": True, "virtual_time_s": self.vt}
        out.update(res)
        return out

    def clear(self, pos, channel):
        self.clear_calls.append((tuple(pos), channel))
        self.vt += 5.0 if self.clear_success else 3.0
        return {"accepted": True, "virtual_time_s": self.vt,
                "clear_result": "success" if self.clear_success else "no_target_in_range"}

    def exit(self):
        return {"accepted": True, "virtual_time_s": self.vt, "exit_reason": "user_exit"}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rep = {"checks": {}, "details": {}}

    def record(key, ok, detail=None):
        rep["checks"][key] = bool(ok)
        if detail is not None:
            rep["details"][key] = detail
        print(f"  [{'PASS' if ok else 'FAIL'}] {key}" + (f"  -> {detail}" if detail is not None else ""))

    src_dec = open(os.path.join(ROOT, "local_decision_frozen.py"), encoding="utf-8").read()
    src_grid = open(os.path.join(ROOT, "conservative_grid_frozen.py"), encoding="utf-8").read()

    print("=" * 108)
    print("【缺陷1】预测角域反向不等号")
    print("=" * 108)
    record("D1_源码无手写角域判据", ("np.dot(rel, n_cw)" not in src_dec and "n_ccw" not in src_dec),
           "删除了重复手写的 n_cw/n_ccw 角域谓词")
    record("D1_预测克隆真实网格并调用真实更新函数",
           ("grid_dir = grid.clone()" in src_dec and "grid_dir.prune_by_direction(" in src_dec),
           "clone() + prune_by_direction()")

    # 行为：预测不得修改原网格
    grid = cgf.ConservativeGrid((999.0, 0.0), 36.96)
    grid.prune_by_direction((1840.0, 0.0), 140.06)   # 得到与 Ch14 一致的实测网格
    before = grid.alive.copy()
    before_n = grid.count()
    dec = ldf.LocalDecisionMaker()
    d = dec.decide_action(cur_p=(1840.0, 0.0), channel=14, grid=grid, followup_count=1,
                          followup_time_s=50.0, force_clear=False, anchor_a=None,
                          measured_positions=[(999.0, 0.0), (1840.0, 0.0)], cur_channel=14,
                          is_p4=True, p1=(999.0, 0.0))
    unchanged = bool(np.array_equal(grid.alive, before))
    record("D1_预测不修改原网格", unchanged and grid.count() == before_n,
           f"调用前后 alive 逐元素一致={unchanged}, cells={before_n}->{grid.count()}")

    # 让评分路径真正运行：使用多步计划的大网格（clear_plan 长度 > 1 才不会走 short_clear_plan 早退）
    g_big = cgf.ConservativeGrid((999.0, 0.0), 0.0)
    plan_big0 = g_big.build_clear_plan((1200.0, 200.0), None)
    d_scored = ldf.LocalDecisionMaker().decide_action(
        cur_p=(1200.0, 200.0), channel=14, grid=g_big, followup_count=1, followup_time_s=50.0,
        force_clear=False, anchor_a=None, measured_positions=[(999.0, 0.0)], cur_channel=14,
        is_p4=True, p1=(999.0, 0.0))
    scored_dir = json.dumps({"plan_len": len(plan_big0), "reason": d_scored["reason"],
                             "j0": d_scored["j0"], "best_jq": d_scored["best_jq"]}, ensure_ascii=False)
    record("D1_评分路径确实运行且无惩罚值",
           (len(plan_big0) > 1 and isinstance(d_scored["j0"], float) and d_scored["j0"] < 1e8
            and (d_scored["best_jq"] is None or (isinstance(d_scored["best_jq"], float)
                                                 and d_scored["best_jq"] < 1e8))),
           scored_dir)

    # 行为：真实观测更新保留真值单元（旧反向判据会剔除）
    true_pt = np.array([1441.945, 333.298])
    g2 = cgf.ConservativeGrid((999.0, 0.0), 36.96)
    g2.prune_by_direction((1840.0, 0.0), 140.06)
    cells = g2.get_surviving_cells()
    dmin = float(np.linalg.norm(cells - true_pt[None, :], axis=1).min())
    record("D1_真实更新保留真值单元", bool(dmin <= g2.d_g),
           f"裁剪后 cells={g2.count()}, 距真值 {dmin:.4f} m <= d_g({g2.d_g:.4f})")

    # 行为：零概率分支不参与评估（p_recv=0 时不得触发真实测向裁剪）
    counter = {"n": 0}
    orig_prune = cgf.ConservativeGrid.prune_by_direction

    def counted(self, *a, **k):
        counter["n"] += 1
        return orig_prune(self, *a, **k)

    cgf.ConservativeGrid.prune_by_direction = counted
    orig_cand = ldf.LocalDecisionMaker.generate_candidates
    try:
        g3 = cgf.ConservativeGrid((999.0, 0.0), 0.0)          # 多步计划的大网格，确保评分路径运行
        surv3 = g3.get_surviving_cells()

        # (a) 全部场景 p_recv = 0：预测期的真实测向裁剪必须一次都不发生
        ldf.LocalDecisionMaker.generate_candidates = lambda self, *a, **k: [(4500.0, 4500.0)]
        counter["n"] = 0
        d3 = ldf.LocalDecisionMaker().decide_action(
            cur_p=(1200.0, 200.0), channel=14, grid=g3, followup_count=1, followup_time_s=50.0,
            force_clear=False, anchor_a=None, measured_positions=[(999.0, 0.0)],
            cur_channel=14, is_p4=True, p1=(999.0, 0.0))
        n_zero = counter["n"]
        ok_zero = (n_zero == 0 and d3["best_jq"] is not None and d3["best_jq"] < 1e8)
        record("D1_零概率分支不参与评估", ok_zero,
               f"全部 d_sc>1500 => p_recv=0 => prune_by_direction 调用={n_zero} 次；"
               f"同时正概率(no_signal)分支已评估 best_jq={d3['best_jq']}")

        # (b) 对照组：候选靠近场景使 p_recv>0，裁剪必须被调用（证明计数器有效，检查非空洞）
        near_q = tuple(float(v) for v in surv3[len(surv3) // 2])
        ldf.LocalDecisionMaker.generate_candidates = lambda self, *a, **k: [near_q]
        counter["n"] = 0
        _ = ldf.LocalDecisionMaker().decide_action(
            cur_p=(1200.0, 200.0), channel=14, grid=g3, followup_count=1, followup_time_s=50.0,
            force_clear=False, anchor_a=None, measured_positions=[(999.0, 0.0)],
            cur_channel=14, is_p4=True, p1=(999.0, 0.0))
        n_pos = counter["n"]
        record("D1_正概率分支确实调用真实更新(对照)", n_pos > 0,
               f"候选靠近场景 => prune_by_direction 调用={n_pos} 次 (对照：零概率时 {n_zero} 次)")
    finally:
        cgf.ConservativeGrid.prune_by_direction = orig_prune
        ldf.LocalDecisionMaker.generate_candidates = orig_cand

    print("=" * 108)
    print("【缺陷2】假想真坐标直接规划清除 / 人为惩罚")
    print("=" * 108)
    record("D2_源码无 plan_dir=[sc] 捷径", ("plan_dir = [tuple(sc)]" not in src_dec), "已删除")
    record("D2_源码无走向 sc 的补偿", ("np.linalg.norm(sc - last)" not in src_dec), "已删除")
    record("D2_源码无人为惩罚常量 1e9 作为评分", ("1e9" not in src_dec.replace("300s/1e9", "").replace("300s / 1e9", "")),
           "评分路径已无 1e9")

    # 行为：成本只由计划动作构成（解析对拍）
    plan = [(100.0, 0.0), (120.0, 0.0), (150.0, 0.0)]
    sc = np.array([151.0, 0.0])
    hit, t = ldf.LocalDecisionMaker._plan_cost_from((0.0, 0.0), plan, sc)
    analytic = (100.0 / 5.0 + 3.0) + (20.0 / 5.0 + 3.0) + (30.0 / 5.0 + 5.0)
    record("D2_成本=计划动作成本(解析对拍)", bool(hit and abs(t - analytic) < 1e-9),
           f"_plan_cost_from={t:.4f}s, 解析值={analytic:.4f}s")

    # 行为：计划无法覆盖场景 -> 显式不可表示（而不是惩罚值）
    costs, ok = ldf.LocalDecisionMaker._eval_plan_on_scenarios(
        (0.0, 0.0), [(5000.0, 5000.0)], [np.array([0.0, 0.0])])
    record("D2_不可表示不注入惩罚", (ok is False and costs == []),
           f"返回 (costs={costs}, ok={ok})，未返回 300s/1e9 之类惩罚")

    print("=" * 108)
    print("【缺陷3】全部存活单元覆盖 / 取消 50 步截断")
    print("=" * 108)
    cov_ok_all = True
    cov_details = []
    for label, g in [("Ch14实测网格", cgf.ConservativeGrid((999.0, 0.0), 36.96)),
                     ("初始大网格", cgf.ConservativeGrid((999.0, 0.0), 0.0))]:
        if label == "Ch14实测网格":
            g.prune_by_direction((1840.0, 0.0), 140.06)
        plan = g.build_clear_plan(tuple(g.p1), None)
        ok_cov, uncovered_n, max_gap = g.verify_full_coverage(plan)
        cov_ok_all = cov_ok_all and ok_cov
        cov_details.append({"grid": label, "cells": g.count(), "plan_len": len(plan),
                            "全覆盖": ok_cov, "未覆盖单元数": uncovered_n,
                            "最大间隙_m": round(max_gap, 5) if max_gap is not None else None})
    record("D3_全部存活单元被计划覆盖", cov_ok_all, json.dumps(cov_details, ensure_ascii=False))

    # 构造需要 > 50 个清除点的网格，验证 50 步截断确实取消
    big = cgf.ConservativeGrid((0.0, 0.0), 0.0)
    plan_big = big.build_clear_plan((0.0, 0.0), None)
    ok_big, unc_big, gap_big = big.verify_full_coverage(plan_big)
    record("D3_取消50步截断", (len(plan_big) > 50 and ok_big),
           f"cells={big.count()}, plan_len={len(plan_big)} (>50), 全覆盖={ok_big}, 未覆盖={unc_big}")

    print("=" * 108)
    print("【缺陷4】补齐 prune_by_near 与合法 near 反馈链")
    print("=" * 108)
    record("D4_冻结网格存在 prune_by_near", hasattr(cgf.ConservativeGrid, "prune_by_near"), "方法已补齐")

    gn = cgf.ConservativeGrid((0.0, 0.0), 0.0)
    cells_n = gn.get_surviving_cells()
    probe = tuple(cells_n[len(cells_n) // 2])
    gn2 = cgf.ConservativeGrid((0.0, 0.0), 0.0)
    before_n2 = gn2.count()
    gn2.prune_by_near(probe)
    kept = gn2.count()
    dists_kept = np.linalg.norm(gn2.get_surviving_cells() - np.array(probe)[None, :], axis=1) if kept else np.array([])
    record("D4_near语义为5m邻域", bool(kept > 0 and np.all(dists_kept - gn2.d_g <= 5.0 + 1e-9)),
           f"cells {before_n2} -> {kept}, 最大 ||z-p|| = {float(dists_kept.max()):.3f} m")

    gn3, gn4 = cgf.ConservativeGrid((0.0, 0.0), 0.0), cgf.ConservativeGrid((0.0, 0.0), 0.0)
    gn3.prune_by_near(probe)
    gn4.prune_by_no_signal_omni(probe)
    record("D4_不套用no_signal距离排除规则", bool(gn3.count() != gn4.count()),
           f"near 后 cells={gn3.count()} vs no_signal_omni 后 cells={gn4.count()}")

    # near 不裁空（矛盾保护仍生效）
    far = (5000.0, 5000.0)
    gn5 = cgf.ConservativeGrid((0.0, 0.0), 0.0)
    n_before = gn5.count()
    gn5.prune_by_near(far)
    record("D4_near不裁空并留痕", bool(gn5.count() == n_before and gn5.rejected_prune_count >= 1),
           f"存活 {n_before} -> {gn5.count()}，rejected_prune_count={gn5.rejected_prune_count}")

    # 端到端：补测返回 near -> prune_by_near -> 原地清除成功
    drv = ScriptedDriver(measure_queue=[{"measure_result": "near"}], clear_success=True)
    eng = StrategyEngine(driver=drv, is_p4=True, version="C", scan_at_clearance=False,
                         enable_2opt_head=False, enable_adaptive_radial_coverage=False, verbose=False)
    eng.start_real_time = 0.0
    st = eng.channels[14]
    st.status = "FOUND"
    st.grid = cgf.ConservativeGrid((999.0, 0.0), 0.0)
    st.measured_positions = [(999.0, 0.0)]
    eng.cur_pos = (999.0, 0.0)
    eng.cur_channel = 14
    real_decide = eng.local_decision.decide_action
    state = {"n": 0}

    def forced(**kw):
        state["n"] += 1
        if state["n"] == 1:
            return {"action_type": "measure", "position": (1300.0, 0.0), "reason": "test_forced_measure",
                    "force_clear": False, "clear_plan": [(1300.0, 0.0)], "j0": 10.0, "best_jq": 5.0,
                    "predicted_feedback": "test", "surviving_cells": kw["grid"].count()}
        return real_decide(**kw)

    eng.local_decision.decide_action = forced
    err = None
    try:
        eng.service_found_target(14)
    except Exception as e:  # 任何缺失方法/属性异常都必须暴露而不是被吞掉
        err = f"{type(e).__name__}: {e}"
    record("D4_near可进入清除且无缺失方法异常",
           (err is None and st.status == "CLEARED" and len(drv.clear_calls) >= 1),
           f"异常={err}, 频道状态={st.status}, clear 调用={drv.clear_calls}")

    # 边界：FOUND 但无测向网格（near 后清除失败的边界情形）——必须走显式失败而不是抛异常
    drv2 = ScriptedDriver(measure_queue=[], clear_success=False)
    eng2 = StrategyEngine(driver=drv2, is_p4=True, version="C", scan_at_clearance=False,
                          enable_2opt_head=False, enable_adaptive_radial_coverage=False, verbose=False)
    eng2.start_real_time = 0.0
    st2 = eng2.channels[7]
    st2.status = "FOUND"
    st2.grid = None
    st2.measured_positions = [(1300.0, 0.0)]
    eng2.cur_pos = (1300.0, 0.0)
    err2 = None
    try:
        eng2.service_found_target(7)
    except Exception as e:
        err2 = f"{type(e).__name__}: {e}"
    record("D4_无网格FOUND走显式失败而非异常",
           (err2 is None and st2.status == "FAILED" and st2.fail_reason == "found_without_bearing_grid"),
           f"异常={err2}, 状态={st2.status}, 原因={st2.fail_reason}")

    ok = all(rep["checks"].values())
    rep["overall_pass"] = ok
    with open(os.path.join(OUT_DIR, "minimal_acceptance.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)

    print("=" * 108)
    print(f"总体判定: {'PASS' if ok else 'FAIL'}   通过 {sum(rep['checks'].values())}/{len(rep['checks'])} 项")
    print(f"[written] {os.path.relpath(os.path.join(OUT_DIR, 'minimal_acceptance.json'), ROOT)}")
    print("=" * 108)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
