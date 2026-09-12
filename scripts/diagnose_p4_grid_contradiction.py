"""
diagnose_p4_grid_contradiction.py - P4 seed=7213 Ch14 最小复现与第一次错误状态变化定位

给定观测（来自既有失败日志）：
  首测 (999, 0)  -> 36.96 deg
  补测 (1840, 0) -> 140.06 deg
两条中心射线交于区域内，距两站均 < 1000 m。

逐步记录：初始化后 / 观测裁剪前后 / decide_action 前后 的存活单元与关键状态，
并逐条判定四类假设。真值（射线交点）仅用于离线验收，不进入策略。

输出：results/p4_fix/diagnosis/minimal_repro_<tag>.json
"""

import sys
import os
import json
import math
import hashlib
import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import conservative_grid_frozen as cgf
import local_decision_frozen as ldf

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "results", "p4_fix", "diagnosis")

P1, TH1 = (999.0, 0.0), 36.96
P2, TH2 = (1840.0, 0.0), 140.06
TAG = sys.argv[1] if len(sys.argv) > 1 else "before"


def sha16(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def ray_intersection(p1, th1, p2, th2):
    a1, a2 = math.radians(th1), math.radians(th2)
    d1 = np.array([math.cos(a1), math.sin(a1)])
    d2 = np.array([math.cos(a2), math.sin(a2)])
    A = np.array([[d1[0], -d2[0]], [d1[1], -d2[1]]])
    b = np.array([p2[0] - p1[0], p2[1] - p1[1]])
    t, s = np.linalg.solve(A, b)
    return np.array(p1) + t * d1, float(t), float(s)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rep = {
        "tag": TAG,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "observations": {"first": {"pos": P1, "bearing_deg": TH1},
                         "followup": {"pos": P2, "bearing_deg": TH2}},
        "ground_truth_offline_only": "射线交点仅用于离线验收，不进入策略",
    }

    print("=" * 104)
    print(f"【P4 最小复现 seed=7213 Ch14】tag={TAG}")
    print("=" * 104)
    print("实际导入文件与哈希:")
    imp = {}
    for mod in (cgf, ldf):
        p = mod.__file__
        imp[os.path.basename(p)] = {"__file__": p, "sha256_16": sha16(p)}
        print(f"  {os.path.basename(p):32s} {sha16(p)}  {p}")
    rep["imported_modules"] = imp

    pt, t, s = ray_intersection(P1, TH1, P2, TH2)
    d1 = float(np.linalg.norm(pt - np.array(P1)))
    d2 = float(np.linalg.norm(pt - np.array(P2)))
    rep["ray_intersection"] = {"point": [round(float(pt[0]), 3), round(float(pt[1]), 3)],
                               "dist_to_first_station_m": round(d1, 2),
                               "dist_to_followup_station_m": round(d2, 2),
                               "dist_to_origin_m": round(float(np.linalg.norm(pt)), 2)}
    print(f"\n两条中心射线交点 = ({pt[0]:.3f}, {pt[1]:.3f})  距首测站 {d1:.2f} m  距补测站 {d2:.2f} m")

    g = cgf.ConservativeGrid(P1, TH1)
    steps = []
    steps.append({"step": "after_init", "alive": g.count(), "total_cells": g.total_cells})
    print(f"\n步骤1 初始化后: 存活单元 {g.count()} / {g.total_cells}")
    cells = g.get_surviving_cells()
    dmin_init = float(np.linalg.norm(cells - pt[None, :], axis=1).min()) if len(cells) else None
    contains_init = bool(dmin_init is not None and dmin_init <= g.d_g)
    print(f"      交点最近单元距离 {dmin_init:.3f} m -> 初始网格包含真值所在单元: {contains_init}")

    before = g.count()
    g.prune_by_direction(P2, TH2)
    after = g.count()
    steps.append({"step": "after_prune_by_direction", "alive": after, "alive_before": before})
    print(f"\n步骤2 实际观测裁剪 prune_by_direction((1840,0), 140.06): {before} -> {after}")
    cells2 = g.get_surviving_cells()
    dmin_p = float(np.linalg.norm(cells2 - pt[None, :], axis=1).min()) if len(cells2) else None
    contains_p = bool(dmin_p is not None and dmin_p <= g.d_g)
    print(f"      交点最近单元距离 {dmin_p if dmin_p is not None else 'N/A'} -> 保留真值所在单元: {contains_p}")

    # 逐子条件核验
    rel = pt - np.array(P2)
    dists = float(np.linalg.norm(rel))
    th_rad, e_rad = math.radians(TH2), math.radians(1.005)
    th_min, th_max = th_rad - e_rad, th_rad + e_rad
    n_cw_frozen = np.array([-math.sin(th_min), math.cos(th_min)])
    n_ccw_frozen = np.array([math.sin(th_max), -math.cos(th_max)])
    dirv = np.array([math.cos(th_rad), math.sin(th_rad)])
    # 旧（错误）判据与修正后判据的对照：旧判据把楔形检验写反
    n1_fixed = np.array([math.sin(th_min), -math.cos(th_min)])
    n2_fixed = np.array([-math.sin(th_max), math.cos(th_max)])
    nf_fixed = np.array([-math.cos(th_rad), -math.sin(th_rad)])
    old_rule_pass = bool(np.dot(rel, n_cw_frozen) <= g.d_g and np.dot(rel, n_ccw_frozen) <= g.d_g
                         and np.dot(rel, dirv) > -g.d_g)
    fixed_rule_pass = bool(np.dot(rel, n1_fixed) <= g.d_g and np.dot(rel, n2_fixed) <= g.d_g
                           and np.dot(rel, nf_fixed) <= g.d_g)
    cond = {
        "dot_rel_n_cw": round(float(np.dot(rel, n_cw_frozen)), 4),
        "dot_rel_n_ccw": round(float(np.dot(rel, n_ccw_frozen)), 4),
        "dot_rel_dir": round(float(np.dot(rel, dirv)), 4),
        "dot_rel_n1_fixed": round(float(np.dot(rel, n1_fixed)), 4),
        "dot_rel_n2_fixed": round(float(np.dot(rel, n2_fixed)), 4),
        "dot_rel_nf_fixed": round(float(np.dot(rel, nf_fixed)), 4),
        "dist_m": round(dists, 3),
        "d_g": round(float(g.d_g), 4),
        "old_rule_keeps_true_cell": old_rule_pass,
        "fixed_rule_keeps_true_cell": fixed_rule_pass,
    }
    rep["intersection_condition_check"] = cond
    print("\n步骤3 交点单元对 prune_by_direction 各子条件的取值:")
    print(f"      dot(rel, n_cw)  = {cond['dot_rel_n_cw']:+.4f}   规则要求 <= d_g({cond['d_g']})  -> "
          f"{'通过' if cond['dot_rel_n_cw'] <= g.d_g else '未通过'}")
    print(f"      dot(rel, n_ccw) = {cond['dot_rel_n_ccw']:+.4f}   规则要求 <= d_g({cond['d_g']})  -> "
          f"{'通过' if cond['dot_rel_n_ccw'] <= g.d_g else '未通过'}")
    print(f"      dot(rel, dir)   = {cond['dot_rel_dir']:+.4f}   旧规则要求 > -d_g        -> "
          f"{'通过' if cond['dot_rel_dir'] > -g.d_g else '未通过'}")
    print(f"      旧判据是否保留真值单元: {old_rule_pass}   修正后判据是否保留真值单元: {fixed_rule_pass}")
    # 该点相对中心射线的角偏
    ang_rel = math.degrees(math.atan2(rel[1], rel[0])) % 360.0
    print(f"      实际方位角 = {ang_rel:.4f} deg (观测 {TH2:.2f} ± 1.005 => [{math.degrees(th_min):.3f}, {math.degrees(th_max):.3f}])")
    _ = ang_rel

    m = ldf.LocalDecisionMaker()
    safe_pos = g.find_safe_clear_position(P2)
    decisions = []
    for label, kw in [("followup_count=1", dict(followup_count=1)),
                      ("followup_count=0", dict(followup_count=0))]:
        dec = m.decide_action(cur_p=P2, channel=14, grid=g, followup_time_s=100.0,
                              force_clear=False, anchor_a=None, measured_positions=[P1, P2],
                              cur_channel=14, is_p4=True, p1=P1, **kw)
        decisions.append({"label": label, "action_type": dec["action_type"], "position": dec["position"],
                          "reason": dec["reason"], "surviving_cells": dec["surviving_cells"]})
        print(f"\n步骤4 decide_action({label}) -> action={dec['action_type']} pos={dec['position']} "
              f"reason={dec['reason']} surviving_cells={dec['surviving_cells']}")
    rep["decide_action"] = decisions
    rep["find_safe_clear_position"] = safe_pos
    rep["check_safe_clear_at"] = bool(g.check_safe_clear_at(P2))
    print(f"      check_safe_clear_at((1840,0)) = {g.check_safe_clear_at(P2)}   "
          f"find_safe_clear_position = {safe_pos}")

    # 四类假设判定
    prune_emptied = (after == 0)
    hyp = {
        "H1_初始化或裁剪错误": {
            "hit": bool(prune_emptied),
            "verdict": ("命中：观测裁剪的角域判据符号写反，合法观测把存活集清空"
                        if prune_emptied else
                        "未再复现：修正后单次合法观测不再清空存活集，且保留真值所在单元"),
            "evidence": (
                f"交点位于观测方位 {TH2}±1.005° 的中心方向上（实际方位 "
                f"{math.degrees(math.atan2(rel[1], rel[0])) % 360.0:.4f}°）。"
                f"旧判据 dot(rel,n_cw)<=d_g 对中心射线上的点取值 "
                f"|rel|·sin(1.005°)={cond['dot_rel_n_cw']:.4f} > d_g={g.d_g:.4f}，"
                f"仅当 |rel| <= d_g/sin(1.005°) ≈ {g.d_g/math.sin(math.radians(1.005)):.1f} m 才可能通过，"
                f"因此任意合法测向观测都会清空存活集。本次实测裁剪: {before} -> {after}。"
            ),
        },
        "H2_预测评估修改了真实网格": {
            "hit": False,
            "verdict": "未命中",
            "evidence": "local_decision_frozen.decide_action 的预测使用 surviving[mask] 局部数组，未对 self.alive 赋值；"
                        "prune_by_* 之外无就地修改。",
        },
        "H3_实际导入了错误副本": {
            "hit": False,
            "verdict": "未命中（导入路径正确，但该冻结副本自身含写反的判据）",
            "evidence": f"实际导入 {os.path.basename(cgf.__file__)} (sha256_16={sha16(cgf.__file__)})；"
                        f"路径正确、无 shadowing。",
        },
        "H4_空网格被误判为 safe_clear_guaranteed": {
            "hit": bool(g.count() == 0),
            "verdict": ("命中：空集被当作安全清除依据" if g.count() == 0 else
                        "未再复现：空集不再构成安全清除依据，决策器不再给出固定点 safe_clear_guaranteed"),
            "evidence": f"check_safe_clear_at = {bool(g.check_safe_clear_at(P2))}；"
                        f"find_safe_clear_position = {safe_pos}；"
                        f"decide_action reason = '{decisions[0]['reason']}'，"
                        f"surviving_cells = {decisions[0]['surviving_cells']}。",
        },
    }
    rep["prune_emptied_grid"] = bool(prune_emptied)
    rep["hypotheses"] = hyp
    print("\n步骤5 四类假设判定:")
    for k, v in hyp.items():
        print(f"      [{k}] hit={v['hit']}  {v['verdict']}")

    rep["first_erroneous_state_change"] = {
        "where": "conservative_grid_frozen.ConservativeGrid.prune_by_direction",
        "first_bad_transition": f"alive {before} -> {after}（首次合法的 direction 观测即清空存活集）",
        "offending_statements": [
            "in_cone = (np.dot(rel, n_cw) <= self.d_g) & (np.dot(rel, n_ccw) <= self.d_g) & (np.dot(rel, dirv) > -self.d_g)",
            "n_cw  = np.array([-math.sin(th_min), math.cos(th_min)])",
            "n_ccw = np.array([math.sin(th_max), -math.cos(th_max)])",
            "def check_safe_clear_at: if len(cells) == 0: return True",
        ],
    }
    rep["steps"] = steps
    rep["grid_state"] = {"after_init": steps[0]["alive"], "after_prune": after,
                         "contains_true_cell_after_init": contains_init,
                         "contains_true_cell_after_prune": contains_p}

    out = os.path.join(OUT_DIR, f"minimal_repro_{TAG}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f"\n[written] {os.path.relpath(out, ROOT)}")
    print("=" * 104)


if __name__ == "__main__":
    main()
