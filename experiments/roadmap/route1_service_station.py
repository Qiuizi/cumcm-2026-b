"""
route1_service_station.py —— 路线1（实际服务测站替代固定覆盖站）的离线可行性研究

【不修改 src/ 下任何 P1–P4 文件；不调用官方模拟器；只使用本地参考环境 src/sim_env.py】

路线1 的现状（先用证据定位缺口）
--------------------------------------------------
`src/strategy_engine.py` 已有两个相关开关/机制，但**彼此没有协同设计**：
  - `scan_at_clearance`（默认 False）：在每个清除点顺路扫描"能在该点新增排除单元的"未决频道；
  - `prune_redundant_search_points`（默认 True）：当某固定搜索点不再能为任何未决频道新增
    排除单元时，把它移出路径规划。
实测（scripts/test_clearance_scan_switch.py，六组配对，见 results/route1_*）：
  打开 `scan_at_clearance` 平均多 57.2 次检测（+340 s 扫描成本），
  只换来 82 s 移动成本下降，净 **+243.9 s 更差**；
  且**访问的固定搜索点数几乎不变**（ON=7/7/5/6/4 vs OFF=7/7/6/7/5）。
  => 额外扫描并没有换来固定测站的取消。这正是路线1 要研究的地方：
     把"在服务测站扫哪些频道"与"取消哪些固定测站"**联合设计**。

本脚本做什么
--------------------------------------------------
用**记录型驱动**（组合包装 LocalSimDriver，不改任何 src 文件）把 `scan_at_clearance=True`
那一条轨迹（下称 ON 轨迹）的每一次 measure/clear 位置、频道、结果、时刻完整录下来，然后离线重放：

  A. 冗余性判定：在 ON 轨迹里，某次固定搜索点访问之前，如果**所有仍未决频道**都已由
     "此前的服务测站静默证据"（清除点 / 补测点，不含固定点本身）完成 168 单元完备证明，
     则该次固定点访问对"空频道认证"是冗余的 —— 它只可能还有"发现新源"的作用，
     而那时所有源都已被发现。
  B. 可省的检测次数：ON 轨迹里在服务测站上对某频道的检测，若检测前后 168 掩码无变化，
     则该次扫描是纯冗余扫描。
  C. 上界：把 A/B 两项折算成虚拟时间与里程，给出路线1 在本批样本上的收益上界，
     并明确指出这**不是**已实现收益（需要新的联合调度器才能落地）。

只读依赖：src.evidence_tracker.EvidenceTrackerP3（用于 168 单元几何），不修改其行为。
"""

import json
import math
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(HERE, "results")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, ROOT)

from src.sim_env import SimEnvironment, LocalSimDriver, SimEnvironment as _SE  # noqa: E402
from src.strategy_engine import StrategyEngine  # noqa: E402
from src.evidence_tracker import EvidenceTrackerP3  # noqa: E402

FIXED_POINTS = [tuple(p) for p in EvidenceTrackerP3().search_points]
R_MIN = 1000.0


class RecordingDriver:
    """包装 LocalSimDriver，逐动作录下 (kind, pos, channel, result, virtual_time)"""

    def __init__(self, driver):
        self._d = driver
        self.trace = []

    def enter(self):
        r = self._d.enter()
        self.trace.append({"kind": "enter", "t": r.get("virtual_time_s", 0.0)})
        return r

    def measure(self, pos, channel):
        r = self._d.measure(pos, channel)
        self.trace.append({
            "kind": "measure",
            "pos": (round(float(pos[0]), 3), round(float(pos[1]), 3)),
            "channel": int(channel),
            "result": r.get("measure_result"),
            "t": float(r.get("virtual_time_s", 0.0)),
        })
        return r

    def clear(self, pos, channel):
        r = self._d.clear(pos, channel)
        self.trace.append({
            "kind": "clear",
            "pos": (round(float(pos[0]), 3), round(float(pos[1]), 3)),
            "channel": int(channel),
            "result": r.get("clear_result"),
            "t": float(r.get("virtual_time_s", 0.0)),
        })
        return r

    def exit(self):
        r = self._d.exit()
        self.trace.append({"kind": "exit", "t": r.get("virtual_time_s", 0.0)})
        return r


def is_fixed_point(pos, tol=5.0):
    for p in FIXED_POINTS:
        if math.hypot(pos[0] - p[0], pos[1] - p[1]) <= tol:
            return True
    return False


def sample_omega(n_theta=360, n_r=120, r_max=1800.0):
    """Ω = B(0,1800) 的极坐标采样"""
    th = np.linspace(0.0, 2.0 * math.pi, n_theta, endpoint=False)
    rs = np.linspace(r_max / n_r, r_max, n_r)
    T, R = np.meshgrid(th, rs)
    return np.stack([(R * np.cos(T)).ravel(), (R * np.sin(T)).ravel()], axis=1)


class MaskReplayer:
    """按时间顺序重放 168 单元静默掩码（只读使用 EvidenceTrackerP3 的几何）"""

    def __init__(self):
        self.tr = EvidenceTrackerP3()
        self.mask = {c: np.zeros(168, dtype=bool) for c in range(1, 21)}

    def apply_no_signal(self, channel, pos):
        before = int(np.sum(self.mask[channel]))
        for idx, cell in enumerate(self.tr.cells):
            if not self.mask[channel][idx]:
                if self.tr.max_distance_to_cell(pos[0], pos[1], cell) <= R_MIN:
                    self.mask[channel][idx] = True
        after = int(np.sum(self.mask[channel]))
        return after - before

    def complete(self, channel):
        return bool(np.all(self.mask[channel]))


def analyse_trace(trace, n_src, absent_channels, unknown_channels_at_end):
    """
    重放 ON 轨迹，产出路线1 的正确判据结果。

    关键判据（留一法 / leave-one-out）：
      固定点 p 对"空频道认证"可省  <=>  把所有空频道的静默测站集合去掉 p 之后，
      该频道仍然能被证明为 ABSENT（168 单元掩码仍完备，或精确 1-覆盖仍成立）。
      只对最终状态为 ABSENT 的频道判定（FOUND/CLEARED 频道不需要空集证明）。

    另含两条辅助量化：
      - 服务测站扫描的"单元级有效性"（每次扫描新增的排除单元数）
      - 去掉固定点 p 后残留的"未认证区域"是否被服务测站覆盖（几何角度，不依赖运行顺序）
    """
    tr = MaskReplayer().tr

    # 1. 各频道静默位置集合（按类型分开）
    silent_fixed = {}    # ch -> [pos, ...] at fixed points
    silent_service = {}  # ch -> [pos, ...] at non-fixed positions
    for ev in trace:
        if ev["kind"] != "measure" or ev.get("result") != "no_signal":
            continue
        ch = ev["channel"]
        if is_fixed_point(ev["pos"]):
            silent_fixed.setdefault(ch, []).append(ev["pos"])
        else:
            silent_service.setdefault(ch, []).append(ev["pos"])

    def mask_of(positions):
        m = np.zeros(168, dtype=bool)
        for pos in positions:
            for idx, cell in enumerate(tr.cells):
                if not m[idx] and tr.max_distance_to_cell(pos[0], pos[1], cell) <= R_MIN:
                    m[idx] = True
        return m

    def complete(positions):
        return bool(np.all(mask_of(positions)))

    def exact_cover(positions):
        """精确 1-覆盖：Ω 上是否存在未被任何 1000 m 圆盘覆盖的采样点"""
        pts = sample_omega(n_theta=180, n_r=60)
        for p in pts:
            x, y = float(p[0]), float(p[1])
            covered = False
            for q in positions:
                if (q[0] - x) ** 2 + (q[1] - y) ** 2 <= (R_MIN + 1e-6) ** 2:
                    covered = True
                    break
            if not covered:
                return False
        return True

    absent = sorted(absent_channels)
    # 固定点是否承担"首次发现源"的职责：承担则不可取消
    discovery_at = {i: [] for i in range(len(FIXED_POINTS))}
    for ev in trace:
        if ev["kind"] == "measure" and ev.get("result") in ("direction", "near"):
            for i, p in enumerate(FIXED_POINTS):
                if math.hypot(ev["pos"][0] - p[0], ev["pos"][1] - p[1]) <= 5.0:
                    discovery_at[i].append(ev["channel"])

    leave_one_out = []
    for i, p in enumerate(FIXED_POINTS):
        detail = {}
        ok_all = True
        for ch in absent:
            positions = [q for q in silent_fixed.get(ch, []) if
                         math.hypot(q[0] - p[0], q[1] - p[1]) > 5.0] + \
                        silent_service.get(ch, [])
            ok = complete(positions)
            if ok:
                ok = exact_cover(positions)
            detail[ch] = bool(ok)
            ok_all = ok_all and bool(ok)
        cancel = bool(ok_all and len(absent) > 0 and not discovery_at[i])
        leave_one_out.append({
            "fixed_point_idx": i,
            "pos": [round(p[0], 2), round(p[1], 2)],
            "channels_first_discovered_here": sorted(set(discovery_at[i])),
            "certificate_ok_without_this_point": bool(ok_all),
            "cancellable": cancel,
            "per_channel_ok": detail,
        })
    absent = sorted(absent_channels)

    # 2. 服务测站扫描的单元级有效性（按时间顺序，独立维护 svc 掩码）
    svc_mask = {c: np.zeros(168, dtype=bool) for c in range(1, 21)}
    total_svc_scans = 0
    useful_svc_scans = 0
    svc_complete_t = {}
    for ev in trace:
        if ev["kind"] != "measure" or ev.get("result") != "no_signal":
            continue
        if is_fixed_point(ev["pos"]):
            continue
        ch = ev["channel"]
        gained = 0
        for idx, cell in enumerate(tr.cells):
            if not svc_mask[ch][idx]:
                if tr.max_distance_to_cell(ev["pos"][0], ev["pos"][1], cell) <= R_MIN:
                    svc_mask[ch][idx] = True
                    gained += 1
        total_svc_scans += 1
        useful_svc_scans += 1 if gained > 0 else 0
        if bool(np.all(svc_mask[ch])) and ch not in svc_complete_t:
            svc_complete_t[ch] = ev["t"]

    # 3. 几何角度：去掉固定点 p 后，7 点网的残留未认证区域有多大、能否被服务测站补上
    pts = sample_omega(n_theta=360, n_r=120)
    svc_positions = [ev["pos"] for ev in trace
                     if ev["kind"] == "measure" and not is_fixed_point(ev["pos"])]
    svc_positions = list({(round(p[0], 3), round(p[1], 3)) for p in svc_positions})
    gap_analysis = []
    for i, p in enumerate(FIXED_POINTS):
        others = [q for j, q in enumerate(FIXED_POINTS) if j != i]
        gap_pts = []
        for s in pts:
            x, y = float(s[0]), float(s[1])
            if all((q[0] - x) ** 2 + (q[1] - y) ** 2 > (R_MIN + 1e-6) ** 2 for q in others):
                gap_pts.append((x, y))
        filled = 0
        for (x, y) in gap_pts:
            for q in svc_positions:
                if (q[0] - x) ** 2 + (q[1] - y) ** 2 <= (R_MIN + 1e-6) ** 2:
                    filled += 1
                    break
        gap_analysis.append({
            "fixed_point_idx": i,
            "gap_samples_after_removal": len(gap_pts),
            "gap_filled_by_service_positions": filled,
            "gap_fill_ratio": round(filled / len(gap_pts), 4) if gap_pts else None,
        })

    # 4. 可取消固定点对应的往返里程（轨迹中相邻位置的位移，作为可省里程的上界）
    pos_seq = [e for e in trace if e["kind"] in ("measure", "clear")]
    total_leg = 0.0
    for a, b in zip(pos_seq, pos_seq[1:]):
        total_leg += math.hypot(b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1])
    cancel_leg = 0.0
    for v in leave_one_out:
        if not v["cancellable"]:
            continue
        p = FIXED_POINTS[v["fixed_point_idx"]]
        for j, e in enumerate(pos_seq):
            if math.hypot(e["pos"][0] - p[0], e["pos"][1] - p[1]) <= 5.0:
                for k in (j - 1, j + 1):
                    if 0 <= k < len(pos_seq):
                        cancel_leg += math.hypot(pos_seq[k]["pos"][0] - p[0],
                                                 pos_seq[k]["pos"][1] - p[1])
                break

    return {
        "n_src": n_src,
        "n_absent_channels": len(absent),
        "leave_one_out": leave_one_out,
        "n_fixed_points_cancellable": sum(1 for v in leave_one_out if v["cancellable"]),
        "n_fixed_points_cert_ok_without": sum(
            1 for v in leave_one_out if v["certificate_ok_without_this_point"]),
        "cancellable_leg_m": round(cancel_leg, 1),
        "total_leg_m": round(total_leg, 1),
        "svc_scans_total": total_svc_scans,
        "svc_scans_useful": useful_svc_scans,
        "svc_scans_redundant": total_svc_scans - useful_svc_scans,
        "svc_scan_unit_efficiency": round(useful_svc_scans / total_svc_scans, 4)
        if total_svc_scans else None,
        "svc_evidence_complete_channels": len(svc_complete_t),
        "gap_analysis": gap_analysis,
        "gap_total_samples": int(len(pts)),
    }


def run_case(n_src, seed, scan_at_clearance, version="C"):
    env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
    rd = RecordingDriver(LocalSimDriver(env))
    eng = StrategyEngine(driver=rd, is_p4=False, version=version,
                         scan_at_clearance=scan_at_clearance, verbose=False)
    res = eng.execute()
    return env, res, rd.trace, eng


def main():
    cases = [(10, 110), (13, 113), (16, 116),
             (10, 4000), (13, 4300), (16, 4600)]

    print("=" * 100)
    print("路线1：实际服务测站替代固定覆盖站 —— 留一法证书重放（P3，本地参考环境）")
    print("=" * 100)

    rows = []
    print(f"{'案例':<22} {'臂':<4} {'T(s)':>9} {'里程(m)':>9} {'检测':>5} {'固定点访问':>8} "
          f"{'可取消固定点':>11} {'服务扫描':>8} {'单元级有效':>9} {'空频道':>6}")
    for n_src, seed in cases:
        for arm in [False, True]:
            env, res, trace, eng = run_case(n_src, seed, arm)
            absent = {ch for ch, st in eng.channels.items() if st.status == "ABSENT"}
            unknown_end = {ch for ch, st in eng.channels.items() if st.status == "UNKNOWN"}
            a = analyse_trace(trace, n_src, absent, unknown_end) if arm else {}
            a.update({
                "case": f"P3-{n_src}src-seed{seed}",
                "arm": "ON" if arm else "OFF",
                "T": round(res["virtual_time_s"], 2),
                "cleared": res["cleared_count"],
                "absent": res["absent_count"],
                "dist_m": round(env.total_distance_m, 1),
                "measures": env.measure_count,
                "search_points_visited": len(res["search_points_visited"]),
            })
            rows.append(a)
            if arm:
                print(f"{a['case']:<22} {'ON':<4} {a['T']:>9.2f} {a['dist_m']:>9.1f} "
                      f"{a['measures']:>5} {a['search_points_visited']:>8} "
                      f"{a['n_fixed_points_cancellable']:>11} {a['svc_scans_total']:>8} "
                      f"{a['svc_scans_useful']:>9} {a['n_absent_channels']:>6}")
            else:
                print(f"{a['case']:<22} {'OFF':<4} {a['T']:>9.2f} {a['dist_m']:>9.1f} "
                      f"{a['measures']:>5} {a['search_points_visited']:>8} "
                      f"{'-':>11} {'-':>8} {'-':>9} {a['absent']:>6}")

    on = [r for r in rows if r["arm"] == "ON"]
    off = [r for r in rows if r["arm"] == "OFF"]

    def mean(key, seq):
        vals = [r[key] for r in seq if r.get(key) is not None]
        return float(np.mean(vals)) if vals else 0.0

    summary = {
        "n_cases": len(cases),
        "on_mean_T": round(mean("T", on), 2),
        "off_mean_T": round(mean("T", off), 2),
        "delta_T_on_minus_off": round(mean("T", on) - mean("T", off), 2),
        "on_mean_measures": round(mean("measures", on), 1),
        "off_mean_measures": round(mean("measures", off), 1),
        "on_mean_search_points_visited": round(mean("search_points_visited", on), 2),
        "off_mean_search_points_visited": round(mean("search_points_visited", off), 2),
        "on_mean_cancellable_fixed_points": round(mean("n_fixed_points_cancellable", on), 3),
        "on_mean_cert_ok_without": round(mean("n_fixed_points_cert_ok_without", on), 3),
        "on_total_leg_m": round(sum(r["total_leg_m"] for r in on), 1),
        "on_cancellable_leg_m": round(sum(r["cancellable_leg_m"] for r in on), 1),
        "on_svc_scans_total": int(sum(r["svc_scans_total"] for r in on)),
        "on_svc_scans_useful": int(sum(r["svc_scans_useful"] for r in on)),
        "on_svc_scans_redundant": int(sum(r["svc_scans_redundant"] for r in on)),
        "on_mean_absent_channels": round(mean("n_absent_channels", on), 2),
        "on_mean_gap_fill_ratio": round(float(np.mean(
            [g["gap_fill_ratio"] if g["gap_fill_ratio"] is not None else 0.0
             for r in on for g in r["gap_analysis"]])), 5),
    }
    summary["on_svc_scan_unit_efficiency"] = round(
        summary["on_svc_scans_useful"] / summary["on_svc_scans_total"], 4
    ) if summary["on_svc_scans_total"] else None

    print("\n" + "=" * 100)
    print("汇总（六案例，ON = scan_at_clearance=True，OFF = 现行默认）")
    print("=" * 100)
    print(f"  平均 T:                       ON {summary['on_mean_T']:.1f}s vs OFF "
          f"{summary['off_mean_T']:.1f}s  (Δ = {summary['delta_T_on_minus_off']:+.1f}s)")
    print(f"  平均检测次数:                 ON {summary['on_mean_measures']:.1f} vs OFF "
          f"{summary['off_mean_measures']:.1f}")
    print(f"  平均访问固定点数:             ON {summary['on_mean_search_points_visited']:.2f} vs OFF "
          f"{summary['off_mean_search_points_visited']:.2f}")
    print(f"  留一法可取消的固定点数:       {summary['on_mean_cancellable_fixed_points']:.3f} "
          f"/ 7（平均每案例；不含承担'首次发现源'职责的固定点）")
    print(f"  仅证书意义上可去掉的固定点数: {summary['on_mean_cert_ok_without']:.3f} / 7")
    print(f"  可取消固定点的往返里程:       {summary['on_cancellable_leg_m']:.0f} m "
          f"/ 全部轨迹里程 {summary['on_total_leg_m']:.0f} m "
          f"({summary['on_cancellable_leg_m'] / summary['on_total_leg_m'] * 100:.1f}%)")
    print(f"  服务测站扫描:                 {summary['on_svc_scans_total']} 次，"
          f"单元级有效 {summary['on_svc_scans_useful']} 次 "
          f"(有效率 {summary['on_svc_scan_unit_efficiency']})")
    print(f"  空频道数（需完备认证的频道）: {summary['on_mean_absent_channels']:.2f} 个/案例")
    print(f"  去掉任一固定点后的残留未认证区域被服务测站填补的比例（平均）: "
          f"{summary['on_mean_gap_fill_ratio']}")
    print(f"  => 结论：单元级有效率 {summary['on_svc_scan_unit_efficiency']}，"
          f"留一法在证书层面可去掉 {summary['on_mean_cert_ok_without']:.2f}/7 个固定点，"
          f"但其中承担'发现源'职责的点不可取消，最终可取消仅 "
          f"{summary['on_mean_cancellable_fixed_points']:.2f}/7。")
    print(f"     且这是**回顾性**上界（用整局累积的服务证据），ON 臂实测净增 "
          f"{summary['delta_T_on_minus_off']:+.1f}s —— 直接开启服务测站扫描是净亏损。")

    with open(os.path.join(OUT_DIR, "route1_service_station_results.json"), "w",
              encoding="utf-8") as f:
        json.dump({"rows": rows, "summary": summary}, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
