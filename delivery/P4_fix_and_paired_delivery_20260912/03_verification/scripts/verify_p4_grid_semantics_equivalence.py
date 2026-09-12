"""
verify_p4_grid_semantics_equivalence.py - 修复后的冻结网格与共享网格的语义等价性核验

目的：证明"修复"不是"换一套实现"，而是把冻结副本中被写反的角域判据改回与共享实现一致的语义。
核验：
  1) _initial_prune 结果逐单元一致
  2) prune_by_direction 在大量合法观测下逐单元一致
  3) 非空网格下 check_safe_clear_at / find_safe_clear_position 一致
  4) 空网格下按修复要求行为正确（冻结副本不再把空集当安全清除依据），
     并如实记录共享副本在空网格下仍保留的历史回退行为（不在 P4 修复范围内）

输出：results/p4_fix/verification/grid_semantics_equivalence.json
"""

import sys
import os
import json
import math

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from conservative_grid_frozen import ConservativeGrid as FrozenGrid
from src.conservative_grid import ConservativeGrid as SharedGrid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "results", "p4_fix", "verification")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rep = {}
    print("=" * 100)
    print("【修复后冻结网格 vs 共享网格 语义等价性核验】")
    print("=" * 100)

    inits = [((999.0, 0.0), 36.96), ((999.0, 0.0), 0.0), ((-999.0, 0.0), 180.0),
             ((0.0, 999.0), 90.0), ((700.0, -700.0), 315.0)]
    init_ok = True
    for p1, th in inits:
        fg, sg = FrozenGrid(p1, th), SharedGrid(p1, th)
        same = bool(np.array_equal(fg.alive, sg.alive))
        init_ok = init_ok and same
        print(f"  初始裁剪 ({p1}, {th:6.2f}°): frozen={fg.count():5d} shared={sg.count():5d} 逐单元一致={same}")
    rep["initial_prune_all_equal"] = bool(init_ok)

    rng = np.random.default_rng(20260912)
    # 合法观测序列对拍：观测方位指向当前存活集内的一个"真值"单元（含 ±1° 测向误差），
    # 这才是策略实际会遇到的观测；随机方位不构成合法观测。
    n_cases = 300
    n_steps = 0
    n_equal = 0
    n_shared_emptied = 0
    n_frozen_rejected = 0
    n_mismatch = 0
    mismatches = []
    for i in range(n_cases):
        p1 = (float(rng.uniform(-800, 800)), float(rng.uniform(-800, 800)))
        th0 = float(rng.uniform(0, 360))
        fg, sg = FrozenGrid(p1, th0), SharedGrid(p1, th0)
        for _ in range(3):
            cells = sg.get_surviving_cells()
            if len(cells) == 0:
                break
            true_pos = cells[int(rng.integers(0, len(cells)))]
            # 合法的测向观测：测站与真值距离位于阳性接收范围内 (5, 1500]，方位含 ±1° 误差
            dist = float(rng.uniform(50.0, 1400.0))
            ang = float(rng.uniform(0.0, 2.0 * math.pi))
            p = (float(true_pos[0] + dist * math.cos(ang)), float(true_pos[1] + dist * math.sin(ang)))
            bearing = math.degrees(math.atan2(true_pos[1] - p[1], true_pos[0] - p[0])) % 360.0
            bearing = (bearing + float(rng.uniform(-1.0, 1.0))) % 360.0
            fg.prune_by_direction(p, bearing)
            sg.prune_by_direction(p, bearing)
            n_steps += 1
            if not np.any(sg.alive):
                n_shared_emptied += 1
                break
            if int(getattr(fg, "rejected_prune_count", 0)) > 0:
                n_frozen_rejected += 1
                break
            if not np.array_equal(fg.alive, sg.alive):
                n_mismatch += 1
                mismatches.append({"case": i, "p": p, "bearing": bearing,
                                   "frozen": fg.count(), "shared": sg.count()})
                break
            n_equal += 1
    print(f"\n  合法观测序列对拍: {n_cases} 组 / {n_steps} 次观测；逐单元一致的更新步数 = {n_equal}")
    print(f"  共享网格被清空的组数 = {n_shared_emptied}；冻结网格拒绝清空裁剪的组数 = {n_frozen_rejected}")
    print(f"  不一致组数 = {n_mismatch}")
    rep["legitimate_observation_pairwise"] = {
        "cases": n_cases, "steps": n_steps, "equal_steps": n_equal,
        "shared_emptied_cases": n_shared_emptied,
        "frozen_rejected_cases": n_frozen_rejected,
        "n_mismatch": n_mismatch, "mismatch_cases": mismatches[:10],
    }

    fg, sg = FrozenGrid((999.0, 0.0), 36.96), SharedGrid((999.0, 0.0), 36.96)
    queries = [(-500.0, 0.0), (500.0, 0.0), (0.0, 0.0), (1000.0, 1000.0)]
    agree = all(fg.check_safe_clear_at(q) == sg.check_safe_clear_at(q) for q in queries)
    rep["non_empty_safe_clear_agreement"] = bool(agree)
    print(f"\n  非空网格下 check_safe_clear_at 一致: {agree}")

    pt = np.array([1441.945, 333.298])
    fg.prune_by_direction((1840.0, 0.0), 140.06)
    cells = fg.get_surviving_cells()
    dmin = float(np.linalg.norm(cells - pt[None, :], axis=1).min())
    rep["ch14_true_cell_retained"] = {
        "surviving_cells": fg.count(),
        "distance_to_true_position_m": round(dmin, 4),
        "retained": bool(dmin <= fg.d_g),
    }
    print(f"\n  seed=7213 Ch14 最小复现: 裁剪后存活 {fg.count()}，距真值 {dmin:.4f} m，"
          f"保留真值单元 = {dmin <= fg.d_g}")

    eg_f, eg_s = FrozenGrid((999.0, 0.0), 36.96), SharedGrid((999.0, 0.0), 36.96)
    eg_f.alive[:] = False
    eg_s.alive[:] = False
    rep["empty_grid_behaviour"] = {
        "frozen_fixed_check_safe_clear_at": bool(eg_f.check_safe_clear_at((0.0, 0.0))),
        "frozen_fixed_find_safe_clear_position": eg_f.find_safe_clear_position((0.0, 0.0)),
        "frozen_fixed_build_clear_plan": eg_f.build_clear_plan((0.0, 0.0)),
        "shared_legacy_check_safe_clear_at": bool(eg_s.check_safe_clear_at((0.0, 0.0))),
        "shared_legacy_find_safe_clear_position": eg_s.find_safe_clear_position((0.0, 0.0)),
        "note": "共享 src/conservative_grid.py 在空网格下仍保留历史回退(True/cur_p)；该分支在 P3 中不可达"
                "（其角域判据正确、网格不会变空），本轮不修改共享组件以保证 P3 合入状态不变。",
    }
    print("\n  空网格行为:")
    for k, v in rep["empty_grid_behaviour"].items():
        print(f"    {k} = {v}")

    out = os.path.join(OUT_DIR, "grid_semantics_equivalence.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    print(f"\n[written] {os.path.relpath(out, ROOT)}")
    print("=" * 100)

    ok = (init_ok and n_mismatch == 0 and n_steps > 0 and agree
          and rep["ch14_true_cell_retained"]["retained"]
          and rep["empty_grid_behaviour"]["frozen_fixed_check_safe_clear_at"] is False
          and rep["empty_grid_behaviour"]["frozen_fixed_find_safe_clear_position"] is None
          and rep["empty_grid_behaviour"]["frozen_fixed_build_clear_plan"] == [])
    print("总体判定:", "PASS" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
