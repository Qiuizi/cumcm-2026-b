"""
strategy_engine.py - 全局调度与求解策略引擎 (v3.3-scan-off-frozen 原样审查副本)
"""

import math
import time
import numpy as np

from src.conservative_grid import ConservativeGrid
from local_decision_frozen import LocalDecisionMaker
from src.evidence_tracker import EvidenceTrackerP3, EvidenceTrackerP4


class ChannelState:
    def __init__(self, channel: int):
        self.channel = channel
        self.status = "UNKNOWN"  # UNKNOWN, FOUND, CLEARED, ABSENT
        self.grid = None
        self.followup_count = 0
        self.followup_time = 0.0
        self.force_clear = False
        self.clear_plan = []
        self.measured_positions = []
        self.first_bearing = None


class StrategyEngine:
    def __init__(
        self,
        driver,  # 可以是直接环境适配器，也可以是 HTTP API client
        is_p4: bool = False,
        version: str = "C",  # "B", "C_BASELINE", "C", "C_OPT", "C_OPENROUTE"
        verbose: bool = False,
        enable_pruning: bool = None,
        scan_at_clearance: bool = False,  # 普通清除点额外扫未知频道开关 (实证表明关闭可省~223s扫描时间)
    ):
        self.driver = driver
        self.is_p4 = is_p4
        self.version = version.upper()
        self.verbose = verbose
        # P4 严格保持冻结状态，不执行清除点额外扫描
        self.scan_at_clearance = scan_at_clearance if not is_p4 else False

        # 是否启用搜索点动态替代剪枝 (根据主要浪费分解进行的单项核心优化)
        if enable_pruning is None:
            self.enable_pruning = (self.version not in ["B", "C_BASELINE", "C_BASE", "BASELINE"])
        else:
            self.enable_pruning = enable_pruning

        self.channels = {c: ChannelState(c) for c in range(1, 21)}
        self.cur_pos = (0.0, 0.0)
        self.cur_channel = 1
        self.virtual_time_s = 0.0

        if not is_p4:
            self.evidence_tracker = EvidenceTrackerP3()
            self.search_points = list(self.evidence_tracker.search_points)
        else:
            self.evidence_tracker = EvidenceTrackerP4()
            self.search_points = list(self.evidence_tracker.all_points)

        self.remaining_search_points = list(self.search_points)
        self.local_decision = LocalDecisionMaker(
            max_followups=12,
            max_followup_time_s=600.0,
            margin_s=5.0,
        )

        # 统计与审计增强
        self.search_points_visited = []
        self.search_points_substituted = []
        self.redundant_search_points_executed = []
        self.movement_logs = []

        self.log_history = []
        self.decision_logs = []
        self.start_real_time = 0.0
        self.end_real_time = 0.0

    def record_movement(self, from_pos: tuple, to_pos: tuple, purpose: str, channel: int = None):
        """记录每次移动的目的与位移"""
        d = math.hypot(to_pos[0] - from_pos[0], to_pos[1] - from_pos[1])
        if d > 1e-3:
            self.movement_logs.append({
                "from": (round(from_pos[0], 2), round(from_pos[1], 2)),
                "to": (round(to_pos[0], 2), round(to_pos[1], 2)),
                "dist_m": round(d, 2),
                "purpose": purpose,
                "channel": channel,
                "virtual_time_s": round(self.virtual_time_s, 2),
            })

    def prune_redundant_search_points(self):
        """
        动态核查并剔除已无新增排除价值的搜索点：
        若某个搜索点已无法为任何当前 UNKNOWN 频道新增排除至少一个 168 单元，
        则认定该搜索点已被实际检测/清除位置替代，从候选集合中动态剔除。
        """
        if self.is_p4:
            return

        # 检查是否全部已决或 K >= 16
        if self.check_completion() or self.get_confirmed_count() >= 16:
            for pt in list(self.remaining_search_points):
                self.remaining_search_points.remove(pt)
                self.search_points_substituted.append(pt)
                self._log(f"全域已决或达K=16上限，搜索点 ({pt[0]:.1f}, {pt[1]:.1f}) 自动标记为被替代/无需访问")
            return

        unknown_channels = [c for c, st in self.channels.items() if st.status == "UNKNOWN"]
        if not unknown_channels:
            for pt in list(self.remaining_search_points):
                self.remaining_search_points.remove(pt)
                self.search_points_substituted.append(pt)
                self._log(f"无未决频道，搜索点 ({pt[0]:.1f}, {pt[1]:.1f}) 自动标记为被替代/无需访问")
            return

        to_remove = []
        for pt in self.remaining_search_points:
            useful = any(self.evidence_tracker.can_eliminate_any_cell(pt, ch) for ch in unknown_channels)
            if not useful:
                to_remove.append(pt)

        for pt in to_remove:
            self.remaining_search_points.remove(pt)
            self.search_points_substituted.append(pt)
            self._log(f"【搜索点被实际检测替代】搜索点 ({pt[0]:.1f}, {pt[1]:.1f}) 对所有未决频道均无新增排除单元，动态移出路径规划")

    def _log(self, msg: str):
        if self.verbose:
            print(f"[{self.virtual_time_s:8.2f}s] {msg}")
        self.log_history.append(f"[{self.virtual_time_s:8.2f}s] {msg}")

    def get_confirmed_count(self) -> int:
        """已确认存在的目标数 K = #{FOUND} + #{CLEARED}"""
        return sum(
            1 for c in self.channels.values() if c.status in ["FOUND", "CLEARED"]
        )

    def check_completion(self) -> bool:
        """检查是否全部频道已决 (CLEARED 或 ABSENT) 或 K == 16"""
        K = self.get_confirmed_count()
        if K >= 16:
            # 其余所有 UNKNOWN 可直接标记 ABSENT
            for ch_state in self.channels.values():
                if ch_state.status == "UNKNOWN":
                    ch_state.status = "ABSENT"

        # 检查是否全部已非 UNKNOWN 且所有 FOUND 均已 CLEARED
        all_resolved = True
        for ch_state in self.channels.values():
            if ch_state.status in ["UNKNOWN", "FOUND"]:
                all_resolved = False
                break
        return all_resolved

    def scan_channels_at_station(self, pos: tuple):
        """在停靠点批量扫描所需 UNKNOWN 频道"""
        channels_to_scan = []
        for ch in range(1, 21):
            st = self.channels[ch]
            if st.status != "UNKNOWN":
                continue
            if not self.is_p4:
                # P3: 必须能新增排除至少一个 168 单元才测
                if self.evidence_tracker.can_eliminate_any_cell(pos, ch):
                    channels_to_scan.append(ch)
            else:
                # P4: 必须是未排除三角形顶点且未测过
                if self.evidence_tracker.needs_measure_at(pos, ch):
                    channels_to_scan.append(ch)

        if not channels_to_scan:
            return

        # 优先当前频道
        if self.cur_channel in channels_to_scan:
            channels_to_scan.remove(self.cur_channel)
            channels_to_scan.insert(0, self.cur_channel)

        for ch in channels_to_scan:
            if self.check_completion():
                break

            # 记录向该停靠点的位移（若有）
            if math.hypot(pos[0] - self.cur_pos[0], pos[1] - self.cur_pos[1]) > 1e-3:
                self.record_movement(self.cur_pos, pos, purpose="VISIT_SEARCH_POINT")

            res = self.driver.measure(pos, ch)
            self.virtual_time_s = res["virtual_time_s"]
            self.cur_pos = pos
            self.cur_channel = ch
            m_res = res["measure_result"]

            if m_res == "direction":
                svd = res["svd_deg"]
                st = self.channels[ch]
                st.status = "FOUND"
                st.first_bearing = svd
                st.grid = ConservativeGrid(pos, svd)
                st.measured_positions.append(pos)
                self._log(f"频道 {ch} 发现目标！示向度 {svd:.2f}°，建立保守网格 (初态 {st.grid.count()} 单元)")
            elif m_res == "near":
                st = self.channels[ch]
                st.status = "FOUND"
                st.measured_positions.append(pos)
                self._log(f"频道 {ch} 触发 near！直接原地清除")
                clr_res = self.driver.clear(pos, ch)
                self.virtual_time_s = clr_res["virtual_time_s"]
                if clr_res["clear_result"] == "success":
                    st.status = "CLEARED"
                    self._log(f"频道 {ch} near 原地清除成功！")
            else:  # no_signal
                self.evidence_tracker.record_no_signal(ch, pos)
                if self.evidence_tracker.is_channel_absent(ch):
                    self.channels[ch].status = "ABSENT"
                    self._log(f"频道 {ch} 全域证据链完整，判定为 ABSENT！")

    def service_found_target(self, channel: int):
        """对 FOUND 目标持续服务直到清除成功"""
        st = self.channels[channel]
        grid = st.grid
        anchor_a = (
            self.remaining_search_points[0]
            if self.remaining_search_points
            else (0.0, 0.0)
        )
        p1 = st.measured_positions[0] if st.measured_positions else (0.0, 0.0)

        while st.status == "FOUND":
            dec = self.local_decision.decide_action(
                cur_p=self.cur_pos,
                channel=channel,
                grid=grid,
                followup_count=st.followup_count,
                followup_time_s=st.followup_time,
                force_clear=st.force_clear,
                anchor_a=anchor_a,
                measured_positions=st.measured_positions,
                cur_channel=self.cur_channel,
                is_p4=self.is_p4,
                p1=p1,
            )

            act_type = dec["action_type"]
            target_pos = dec["position"]
            st.force_clear = dec["force_clear"]

            # 记录详细决策日志
            d_log_entry = {
                "virtual_time_s": round(self.virtual_time_s, 2),
                "channel": channel,
                "action_type": act_type,
                "position": (round(target_pos[0], 2), round(target_pos[1], 2)),
                "reason": dec["reason"],
                "j0": round(dec["j0"], 2),
                "best_jq": round(dec["best_jq"], 2) if dec["best_jq"] < 1e8 else None,
                "predicted_feedback": dec.get("predicted_feedback", ""),
                "cells_before": dec.get("surviving_cells", grid.count()),
                "followup_count": st.followup_count,
            }

            if act_type == "measure":
                self.record_movement(self.cur_pos, target_pos, purpose="TARGET_FOLLOWUP", channel=channel)
                t_before = self.virtual_time_s
                res = self.driver.measure(target_pos, channel)
                self.virtual_time_s = res["virtual_time_s"]
                self.cur_pos = target_pos
                self.cur_channel = channel
                m_time = self.virtual_time_s - t_before
                st.followup_count += 1
                st.followup_time += m_time
                st.measured_positions.append(target_pos)

                m_res = res["measure_result"]
                d_log_entry["actual_result"] = m_res

                if m_res == "direction":
                    svd = res["svd_deg"]
                    d_log_entry["svd_deg"] = svd
                    grid.prune_by_direction(target_pos, svd)
                    d_log_entry["cells_after"] = grid.count()
                    self._log(f"目标 {channel} 补测 {st.followup_count} 次: 读数 {svd:.2f}°，存活单元收缩至 {grid.count()} (Jq={dec['best_jq']:.1f}s vs J0={dec['j0']:.1f}s)")
                elif m_res == "near":
                    grid.prune_by_near(target_pos)
                    d_log_entry["cells_after"] = grid.count()
                    self._log(f"目标 {channel} 补测触发 near！转入原地清除")
                    c_res = self.driver.clear(target_pos, channel)
                    self.virtual_time_s = c_res["virtual_time_s"]
                    if c_res["clear_result"] == "success":
                        st.status = "CLEARED"
                        self._log(f"★ 目标 {channel} 清除成功！")
                        self.decision_logs.append(d_log_entry)
                        break
                else:  # no_signal
                    if not self.is_p4:
                        grid.prune_by_no_signal_omni(target_pos)
                    d_log_entry["cells_after"] = grid.count()
                    self._log(f"目标 {channel} 补测 no_signal，存活单元保持 {grid.count()} (Jq={dec['best_jq']:.1f}s vs J0={dec['j0']:.1f}s)")

                self.decision_logs.append(d_log_entry)

            elif act_type == "clear":
                # 执行清除动作
                plan = dec["clear_plan"]
                d_log_entry["plan_len"] = len(plan)
                self.decision_logs.append(d_log_entry)

                for pt in plan:
                    self.record_movement(self.cur_pos, pt, purpose="TARGET_CLEAR", channel=channel)
                    t_before = self.virtual_time_s
                    res = self.driver.clear(pt, channel)
                    self.virtual_time_s = res["virtual_time_s"]
                    self.cur_pos = pt
                    c_res = res["clear_result"]

                    if c_res == "success":
                        st.status = "CLEARED"
                        self._log(f"★ 目标 {channel} 在位置 ({pt[0]:.1f}, {pt[1]:.1f}) 清除成功！")
                        break
                    else:
                        grid.prune_by_clear_fail(pt)
                        self._log(f"目标 {channel} 在 ({pt[0]:.1f}, {pt[1]:.1f}) 清除未命中，保守剔除20m圆，剩余单元 {grid.count()}")

                if st.status == "CLEARED":
                    break

        # 清除成功后，在当前清除点顺路批量扫描 UNKNOWN 频道 (受 scan_at_clearance 开关控制)
        if not self.is_p4 and st.status == "CLEARED" and self.scan_at_clearance:
            self.scan_channels_at_station(self.cur_pos)
            if self.enable_pruning:
                self.prune_redundant_search_points()

    def run_version_b(self):
        """版本 B：固定覆盖顺序基线"""
        self._log(">>> 启动方案版本 B (稳定基线：固定覆盖顺序) <<<")

        # 1. 原点首扫
        self.scan_channels_at_station((0.0, 0.0))

        # 2. 循环处理直至全部解决
        while not self.check_completion():
            # 优先处理所有已发现目标
            found_channels = [
                c for c, st in self.channels.items() if st.status == "FOUND"
            ]
            if found_channels:
                found_channels.sort(
                    key=lambda c: np.linalg.norm(
                        np.mean(self.channels[c].grid.get_surviving_cells(), axis=0)
                        - np.array(self.cur_pos)
                    )
                )
                target_ch = found_channels[0]
                self._log(f"调度：开始服务已发现目标 {target_ch}")
                self.service_found_target(target_ch)
                continue

            # 若暂无 FOUND 目标，前往下一个未完成的搜索点
            if self.remaining_search_points:
                next_pt = self.remaining_search_points.pop(0)
                self._log(f"调度：前往固定搜索基准点 ({next_pt[0]:.1f}, {next_pt[1]:.1f})")
                self.scan_channels_at_station(next_pt)
            else:
                break

    def run_version_c_greedy(self):
        """版本 C_greedy：最近邻贪心调度对照基线"""
        self._log(">>> 启动方案版本 C_greedy (对照：最近邻贪心调度) <<<")

        # 1. 原点首扫
        self.scan_channels_at_station((0.0, 0.0))

        while not self.check_completion():
            found_channels = [
                c for c, st in self.channels.items() if st.status == "FOUND"
            ]

            if not found_channels and not self.remaining_search_points:
                break

            tasks = []
            for ch in found_channels:
                cells = self.channels[ch].grid.get_surviving_cells()
                rep_pos = np.mean(cells, axis=0) if len(cells) > 0 else self.cur_pos
                tasks.append({
                    "type": "target",
                    "channel": ch,
                    "pos": (float(rep_pos[0]), float(rep_pos[1])),
                })

            for idx, pt in enumerate(self.remaining_search_points):
                tasks.append({
                    "type": "search",
                    "point_idx": idx,
                    "pos": pt,
                })

            cur = np.array(self.cur_pos)
            best_task = None
            best_d = 1e9
            for t in tasks:
                d = np.linalg.norm(np.array(t["pos"]) - cur)
                if d < best_d:
                    best_d = d
                    best_task = t

            if best_task["type"] == "target":
                ch = best_task["channel"]
                self._log(f"贪心调度：选择最近目标任务 {ch} (估计距离 {best_d:.1f}m)")
                self.service_found_target(ch)
            else:
                pt = best_task["pos"]
                self.remaining_search_points.remove(pt)
                self._log(f"贪心调度：选择最近搜索任务 ({pt[0]:.1f}, {pt[1]:.1f}) (估计距离 {best_d:.1f}m)")
                self.scan_channels_at_station(pt)

    def run_version_c_openroute(self):
        """版本 C / C_openroute：开放路线重排 (Nearest Insertion + 2-Opt 启发式)"""
        ver_tag = "C_OPT" if self.enable_pruning else "C_BASELINE"
        self._log(f">>> 启动方案版本 {ver_tag} (开放路线重排 | 动态剪枝={self.enable_pruning}) <<<")

        # 1. 原点首扫
        self.scan_channels_at_station((0.0, 0.0))
        if self.enable_pruning:
            self.prune_redundant_search_points()

        while not self.check_completion():
            if self.enable_pruning:
                self.prune_redundant_search_points()

            found_channels = [
                c for c, st in self.channels.items() if st.status == "FOUND"
            ]

            if not found_channels and not self.remaining_search_points:
                break

            tasks = []
            for ch in found_channels:
                cells = self.channels[ch].grid.get_surviving_cells()
                rep_pos = np.mean(cells, axis=0) if len(cells) > 0 else self.cur_pos
                tasks.append({
                    "type": "target",
                    "channel": ch,
                    "pos": (float(rep_pos[0]), float(rep_pos[1])),
                })

            for idx, pt in enumerate(self.remaining_search_points):
                tasks.append({
                    "type": "search",
                    "point_idx": idx,
                    "pos": pt,
                })

            if len(tasks) == 1:
                best_task = tasks[0]
            else:
                # 构造开放路径：起点为 cur_pos，采用最近插入法构造巡检链路
                cur = np.array(self.cur_pos)
                unvisited = list(range(len(tasks)))
                
                # 初始选取离起点最近的节点
                first_idx = min(unvisited, key=lambda i: np.linalg.norm(np.array(tasks[i]["pos"]) - cur))
                path = [first_idx]
                unvisited.remove(first_idx)

                # 逐步插入剩余节点使路径增量最小
                while unvisited:
                    best_candidate = None
                    best_insert_pos = None
                    best_cost = 1e9

                    for cand in unvisited:
                        cand_pos = np.array(tasks[cand]["pos"])
                        # 插入头部：cur -> cand -> path[0]
                        c_head = np.linalg.norm(cand_pos - cur) + np.linalg.norm(np.array(tasks[path[0]]["pos"]) - cand_pos) - np.linalg.norm(np.array(tasks[path[0]]["pos"]) - cur)
                        if c_head < best_cost:
                            best_cost = c_head
                            best_candidate = cand
                            best_insert_pos = 0

                        # 插入中间位置
                        for p in range(len(path) - 1):
                            p1_p = np.array(tasks[path[p]]["pos"])
                            p2_p = np.array(tasks[path[p + 1]]["pos"])
                            c_mid = np.linalg.norm(p1_p - cand_pos) + np.linalg.norm(cand_pos - p2_p) - np.linalg.norm(p1_p - p2_p)
                            if c_mid < best_cost:
                                best_cost = c_mid
                                best_candidate = cand
                                best_insert_pos = p + 1

                        # 插入尾部
                        p_tail = np.array(tasks[path[-1]]["pos"])
                        c_tail = np.linalg.norm(cand_pos - p_tail)
                        if c_tail < best_cost:
                            best_cost = c_tail
                            best_candidate = cand
                            best_insert_pos = len(path)

                    path.insert(best_insert_pos, best_candidate)
                    unvisited.remove(best_candidate)

                # 局部 2-opt 改善开放路径 (最多 15 次交换)
                improved = True
                opt_iter = 0
                while improved and opt_iter < 15:
                    improved = False
                    opt_iter += 1
                    for i in range(len(path) - 1):
                        for j in range(i + 2, len(path)):
                            # 评估交换 [i+1:j] 子段
                            p_i = cur if i == -1 else np.array(tasks[path[i]]["pos"])
                            p_i1 = np.array(tasks[path[i + 1]]["pos"])
                            p_j = np.array(tasks[path[j]]["pos"])
                            p_j1 = np.array(tasks[path[j + 1]]["pos"]) if j + 1 < len(path) else None

                            d_old = np.linalg.norm(p_i - p_i1)
                            if p_j1 is not None:
                                d_old += np.linalg.norm(p_j - p_j1)

                            d_new = np.linalg.norm(p_i - p_j)
                            if p_j1 is not None:
                                d_new += np.linalg.norm(p_i1 - p_j1)

                            if d_new < d_old - 1e-3:
                                path[i + 1 : j + 1] = reversed(path[i + 1 : j + 1])
                                improved = True
                                break
                        if improved:
                            break

                best_task = tasks[path[0]]

            if best_task["type"] == "target":
                ch = best_task["channel"]
                d_est = np.linalg.norm(np.array(best_task["pos"]) - np.array(self.cur_pos))
                self._log(f"开放路线调度：选择任务链路首目标 {ch} (估计距离 {d_est:.1f}m)")
                self.service_found_target(ch)
            else:
                pt = best_task["pos"]
                self.remaining_search_points.remove(pt)
                d_est = np.linalg.norm(np.array(pt) - np.array(self.cur_pos))

                # 核查是否存在“覆盖证据已经足够，却仍执行固定搜索点”的行为 (仅在 P3 核查)
                if not self.is_p4:
                    unknown_channels = [c for c, st in self.channels.items() if st.status == "UNKNOWN"]
                    is_redundant = not any(self.evidence_tracker.can_eliminate_any_cell(pt, ch) for ch in unknown_channels)
                    if is_redundant:
                        self.redundant_search_points_executed.append(pt)
                        self._log(f"【基线浪费核查告警】搜索点 ({pt[0]:.1f}, {pt[1]:.1f}) 覆盖证据已完全充分 (0个新增排除单元)，但基线仍执行前往！(预计空跑距离 {d_est:.1f}m)")

                self.search_points_visited.append(pt)
                self._log(f"开放路线调度：选择任务链路首搜索点 ({pt[0]:.1f}, {pt[1]:.1f}) (估计距离 {d_est:.1f}m)")
                self.scan_channels_at_station(pt)
                if self.enable_pruning:
                    self.prune_redundant_search_points()

    def execute(self):
        """执行完整求解任务并退出"""
        self.start_real_time = time.time()
        self.driver.enter()

        if self.version == "B":
            self.run_version_b()
        elif self.version in ["C_GREEDY", "GREEDY"]:
            self.run_version_c_greedy()
        else:
            self.run_version_c_openroute()

        self.driver.exit()
        self.end_real_time = time.time()

        # 统计指标
        cleared_count = sum(1 for st in self.channels.values() if st.status == "CLEARED")
        absent_count = sum(1 for st in self.channels.values() if st.status == "ABSENT")
        unsolved_count = sum(1 for st in self.channels.values() if st.status in ["UNKNOWN", "FOUND"])
        real_time_s = self.end_real_time - self.start_real_time

        summary = {
            "version": self.version,
            "is_p4": self.is_p4,
            "enable_pruning": self.enable_pruning,
            "scan_at_clearance": self.scan_at_clearance,
            "virtual_time_s": self.virtual_time_s,
            "real_time_s": real_time_s,
            "cleared_count": cleared_count,
            "absent_count": absent_count,
            "unsolved_count": unsolved_count,
            "avg_time_per_target": (self.virtual_time_s / cleared_count) if cleared_count > 0 else 0.0,
            "decision_count": len(self.decision_logs),
            "search_points_visited_count": len(self.search_points_visited),
            "search_points_visited": self.search_points_visited,
            "search_points_substituted_count": len(self.search_points_substituted),
            "search_points_substituted": self.search_points_substituted,
            "redundant_search_points_executed_count": len(self.redundant_search_points_executed),
            "redundant_search_points_executed": self.redundant_search_points_executed,
            "movement_count": len(self.movement_logs),
            "total_move_dist_m": sum(m["dist_m"] for m in self.movement_logs),
        }
        return summary
