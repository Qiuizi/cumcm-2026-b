"""
strategy_engine.py - 全局调度与求解策略引擎
支持：
1. 问题三 (P3): 7点覆盖 + 168扇形单元证据
2. 问题四 (P4): 25点覆盖 + 32三角形证据
3. 版本 B (固定覆盖基线)、版本 C_greedy (局部贪心最近邻)、版本 C / C_openroute (开放路线启发式重排)
4. 闭环决策日志审计 (J0, J(q), 预测反馈, 测前后单元数)
"""

import math
import time
import numpy as np

from src.conservative_grid import ConservativeGrid
from src.local_decision import LocalDecisionMaker
from src.evidence_tracker import EvidenceTrackerP3, EvidenceTrackerP4


class ChannelState:
    def __init__(self, channel: int):
        self.channel = channel
        self.status = "UNKNOWN"  # UNKNOWN, FOUND, CLEARED, ABSENT, FAILED
        # FAILED 表示"已按合法路径显式判失败"，不等于 ABSENT(不存在) 也不等于 CLEARED(已清除)
        self.fail_reason = None
        self.absence_proof_type = None  # None, "COVERAGE_NEGATIVE", "UPPER_BOUND_EXCLUSION"
        self.grid = None
        self.followup_count = 0
        self.followup_time = 0.0
        self.force_clear = False
        self.clear_plan = []
        self.measured_positions = []
        self.first_bearing = None
        self.last_failed_clear_pos = None      # 最近一次清除失败的位置（用于重复失败熔断）
        self.repeat_clear_fail_count = 0       # 同位置同频道且状态不变的连续清除失败次数


def describe_task(task: dict) -> dict:
    """把调度任务描述为可审计标识 (用于对比 2-opt 前后的首任务)"""
    pos = task["pos"]
    base = {
        "type": task["type"],
        "pos": [round(float(pos[0]), 2), round(float(pos[1]), 2)],
    }
    if task["type"] == "target":
        base["channel"] = int(task["channel"])
    else:
        base["point_idx"] = int(task["point_idx"])
    return base


class StrategyEngine:
    def __init__(
        self,
        driver,  # 可以是直接环境适配器，也可以是 HTTP API client
        is_p4: bool = False,
        version: str = "C",  # "B", "C_BASELINE", "C", "C_OPT", "C_OPENROUTE"
        verbose: bool = False,
        enable_pruning: bool = None,
        scan_at_clearance: bool = False,  # 普通清除点额外扫未知频道开关 (实证表明关闭可省~223s扫描时间)
        enable_2opt_head: bool = False,  # 允许2-opt优化改变首任务的独立开关
        enable_adaptive_radial_coverage: bool = False,  # P3沿原射线可移动检测点独立开关
        max_repeat_clear_fail: int = 3,  # 同位置同频道且状态不变的连续清除失败熔断阈值
    ):
        self.driver = driver
        self.is_p4 = is_p4
        self.version = version.upper()
        self.verbose = verbose
        # P4 冻结项：清除点额外扫描与径向自适应覆盖仍在 P4 下强制关闭（本届实验不改动）
        self.scan_at_clearance = scan_at_clearance if not is_p4 else False
        # 【P4 实验分支唯一变量】解除 P4 对 enable_2opt_head 的强制覆盖：
        # 参数默认值仍为 False（默认继续关闭），仅当调用方显式传入 True 时才允许
        # 开放路线的 2-opt 改变最终实际派发的首任务。除此以外 P4 行为完全不变。
        self.enable_2opt_head = enable_2opt_head
        self.enable_adaptive_radial_coverage = enable_adaptive_radial_coverage if not is_p4 else False

        # 是否启用搜索点动态替代剪枝 (根据主要浪费分解进行的单项核心优化)
        if enable_pruning is None:
            self.enable_pruning = (self.version not in ["B", "C_BASELINE", "C_BASE", "BASELINE"])
        else:
            self.enable_pruning = enable_pruning

        self.channels = {c: ChannelState(c) for c in range(1, 21)}
        self.cur_pos = (0.0, 0.0)
        self.cur_channel = 1
        self.virtual_time_s = 0.0
        self.dispatched_head_change_count = 0  # 统计2-opt导致最终实际派发首任务变更的轮数
        self.total_2opt_swaps = 0              # 统计2-opt内部交换/翻转的总次数
        self.radial_adjustments_count = 0      # 统计沿射线调整覆盖检测位置的次数
        self.radial_events = []                # 记录详细径向覆盖调点审计快照
        # 终止与完成状态：区分"成功完成"与"预算安全退出"，不伪造完成
        self.completion_status = "NOT_STARTED"     # COMPLETED / SAFE_EXIT_BUDGET / INCOMPLETE
        self.terminal_reason = None
        self.max_virtual_duration_s = None
        self.max_real_duration_s = None
        self.failed_targets = []                   # 显式判失败的目标记录
        self.max_repeat_clear_fail = int(max_repeat_clear_fail)
        self.head_dispatch_records = []        # 逐轮记录"2-opt 前后首任务"，用于统计真正改变下一动作的次数

        if not is_p4:
            self.evidence_tracker = EvidenceTrackerP3()
            self.search_points = list(self.evidence_tracker.search_points)
            self.local_decision = LocalDecisionMaker(
                max_followups=12,
                max_followup_time_s=600.0,
                margin_s=5.0,
            )
            self.grid_class = ConservativeGrid
        else:
            self.evidence_tracker = EvidenceTrackerP4()
            self.search_points = list(self.evidence_tracker.all_points)
            # P4 实际仍使用冻结实现，共享模块修改不连带改变其行为
            import local_decision_frozen
            import conservative_grid_frozen
            self.local_decision = local_decision_frozen.LocalDecisionMaker(
                max_followups=12,
                max_followup_time_s=600.0,
                margin_s=5.0,
            )
            self.grid_class = conservative_grid_frozen.ConservativeGrid

        self.remaining_search_points = list(self.search_points)

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

    def resolve_remaining_as_upper_bound_exclusion(self):
        """当已确认16个干扰源时，根据赛题[10,16]上限先验将所有剩余 UNKNOWN 频道直接排除为 ABSENT"""
        for ch, st in self.channels.items():
            if st.status == "UNKNOWN":
                st.status = "ABSENT"
                st.absence_proof_type = "UPPER_BOUND_EXCLUSION"
                self._log(f"频道 {ch}：已确认源达到16个上限，根据总数上限直接排除为 ABSENT！")

    def check_completion(self) -> bool:
        """检查是否全部频道已决 (CLEARED 或 ABSENT)；若已达16源上限处理剩余UNKNOWN并继续清除FOUND"""
        K = self.get_confirmed_count()
        if K >= 16:
            self.resolve_remaining_as_upper_bound_exclusion()

        # 检查是否全部已非 UNKNOWN 且所有 FOUND 均已 CLEARED
        all_resolved = True
        for ch_state in self.channels.values():
            if ch_state.status in ["UNKNOWN", "FOUND"]:
                all_resolved = False
                break
        return all_resolved

    def scan_channels_at_station(self, pos: tuple):
        """在停靠点批量扫描所需 UNKNOWN 频道"""
        # 准备扫描批次前重新检查：若已确认16个源，立即结束未知频道扫描并按上限排除
        if self.get_confirmed_count() >= 16:
            self.resolve_remaining_as_upper_bound_exclusion()
            return

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
            # 每次准备扫描具体 UNKNOWN 频道前重新检查
            if self.get_confirmed_count() >= 16:
                self.resolve_remaining_as_upper_bound_exclusion()
                break

            # 再次核验该频道当前状态 (防止在循环过程中状态变更)
            if self.channels[ch].status != "UNKNOWN":
                continue

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
                st.grid = self.grid_class(pos, svd)
                st.measured_positions.append(pos)
                self._log(f"频道 {ch} 发现目标！示向度 {svd:.2f}°，建立保守网格 (初态 {st.grid.count()} 单元)")
                if self.get_confirmed_count() >= 16:
                    self.resolve_remaining_as_upper_bound_exclusion()
                    break
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
                if self.get_confirmed_count() >= 16:
                    self.resolve_remaining_as_upper_bound_exclusion()
                    break
            else:  # no_signal
                self.evidence_tracker.record_no_signal(ch, pos)
                if self.evidence_tracker.is_channel_absent(ch):
                    st = self.channels[ch]
                    st.status = "ABSENT"
                    st.absence_proof_type = "COVERAGE_NEGATIVE"
                    cov_desc = "168单元覆盖完备" if not self.is_p4 else "三角形网格覆盖完备"
                    self._log(f"频道 {ch} 实际阴性观测完成覆盖 ({cov_desc})，判定为 ABSENT！")

    def _budget_exhausted(self):
        """现实/虚拟预算检查。返回 (是否耗尽, 终止原因)。"""
        if self.max_virtual_duration_s is not None and self.virtual_time_s >= self.max_virtual_duration_s:
            return True, "VIRTUAL_BUDGET_EXHAUSTED"
        if self.max_real_duration_s is not None and (time.time() - self.start_real_time) >= self.max_real_duration_s:
            return True, "REAL_BUDGET_EXHAUSTED"
        return False, None

    def _check_budget_or_stop(self) -> bool:
        """预算耗尽时记录终止原因并返回 True（调用方应 break，按合法退出路径结束）"""
        exhausted, reason = self._budget_exhausted()
        if exhausted:
            self.terminal_reason = reason
            self._log(
                f"【预算终止】{reason}: 虚拟时间 {self.virtual_time_s:.1f}s / "
                f"现实耗时 {time.time() - self.start_real_time:.1f}s —— 安全退出（非成功完成）"
            )
            return True
        return False

    def _fail_channel(self, channel: int, reason: str):
        """显式判失败：不以 ABSENT/CLEARED 伪造完成，保留已有观测与有效状态。"""
        st = self.channels[channel]
        st.status = "FAILED"
        st.fail_reason = reason
        self.failed_targets.append({
            "channel": channel,
            "reason": reason,
            "virtual_time_s": round(self.virtual_time_s, 2),
            "measured_positions": len(st.measured_positions),
            "followup_count": st.followup_count,
            "surviving_cells": (st.grid.count() if st.grid is not None else None),
            "grid_contradiction": bool(getattr(st.grid, "contradiction", False)) if st.grid is not None else None,
        })
        self._log(f"【目标失败】频道 {channel}: {reason} —— 显式标记失败，不伪造 ABSENT/CLEARED")

    def service_found_target(self, channel: int):
        """对 FOUND 目标持续服务直到清除成功"""
        st = self.channels[channel]
        grid = st.grid

        # 【缺陷4 配套】该目标只有 near 观测、还没有测向网格
        # （例如搜索点直接触发 near 且原地清除未成功的边界情形）：
        # 用已有观测做一次合法的原地清除恢复；无法恢复则显式判失败，
        # 既不抛出缺失方法/属性异常，也不伪造 ABSENT/CLEARED。
        if grid is None:
            if st.measured_positions:
                rec_pos = st.measured_positions[-1]
                self.record_movement(self.cur_pos, rec_pos, purpose="NEAR_OBSERVATION_RECOVERY", channel=channel)
                res = self.driver.clear(rec_pos, channel)
                self.virtual_time_s = res["virtual_time_s"]
                self.cur_pos = rec_pos
                if res["clear_result"] == "success":
                    st.status = "CLEARED"
                    self._log(f"★ 目标 {channel} 依据已有 near 观测在 ({rec_pos[0]:.1f}, {rec_pos[1]:.1f}) 清除成功！")
                    return
            self._fail_channel(channel, "found_without_bearing_grid")
            return

        anchor_a = (
            self.remaining_search_points[0]
            if self.remaining_search_points
            else (0.0, 0.0)
        )
        p1 = st.measured_positions[0] if st.measured_positions else (0.0, 0.0)

        while st.status == "FOUND":
            # 现实/虚拟预算检查：耗尽即显式判失败并按合法路径结束，不伪造完成
            exhausted, budget_reason = self._budget_exhausted()
            if exhausted:
                self._fail_channel(channel, f"budget_exhausted:{budget_reason}")
                break

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
            target_pos = tuple(dec["position"])
            st.force_clear = dec["force_clear"]

            # 决策器显式判失败（空网格 / 模型矛盾 / 无合法清除计划）：
            # 该状态不得被解释为"目标不存在"或"目标已清除"，也不得伪造完成。
            if act_type == "fail":
                d_log_entry = {
                    "virtual_time_s": round(self.virtual_time_s, 2),
                    "channel": channel,
                    "action_type": "fail",
                    "position": (round(target_pos[0], 2), round(target_pos[1], 2)),
                    "reason": dec["reason"],
                    "j0": 0.0,
                    "best_jq": None,
                    "predicted_feedback": "none",
                    "cells_before": dec.get("surviving_cells", grid.count()),
                    "followup_count": st.followup_count,
                    "actual_result": "model_failure",
                }
                self.decision_logs.append(d_log_entry)
                self._fail_channel(channel, dec.get("reason", "decision_failure"))
                break

            # 记录详细决策日志
            d_log_entry = {
                "virtual_time_s": round(self.virtual_time_s, 2),
                "channel": channel,
                "action_type": act_type,
                "position": (round(target_pos[0], 2), round(target_pos[1], 2)),
                "reason": dec["reason"],
                "j0": round(dec["j0"], 2),
                "best_jq": (round(dec["best_jq"], 2)
                            if isinstance(dec.get("best_jq"), (int, float)) and dec["best_jq"] < 1e8
                            else None),
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

                cells_before_plan = grid.count()
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

                # 重复失败熔断：同位置、同频道清除失败且状态（存活集）不变时，不再无限重复
                if len(plan) == 1:
                    sign = (round(float(plan[0][0]), 2), round(float(plan[0][1]), 2))
                    unchanged = (grid.count() == cells_before_plan)
                    if unchanged and st.last_failed_clear_pos == sign:
                        st.repeat_clear_fail_count += 1
                    else:
                        st.repeat_clear_fail_count = 1 if unchanged else 0
                    st.last_failed_clear_pos = sign
                    if st.repeat_clear_fail_count >= self.max_repeat_clear_fail:
                        self._fail_channel(channel, "repeated_clear_fail_no_state_change")
                        break
                else:
                    st.repeat_clear_fail_count = 0
                    st.last_failed_clear_pos = None

        # 清除成功后，在当前清除点顺路批量扫描 UNKNOWN 频道 (受 scan_at_clearance 控制)
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
            if self._check_budget_or_stop():
                break
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
            if self._check_budget_or_stop():
                break

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

    def _select_radial_search_point(
        self,
        ray_idx: int,
        theta: float,
        nom_pt: tuple,
        next_pos: tuple = None,
    ) -> tuple[float, tuple, dict]:
        """
        在给定射线 theta_i 沿向选择候选半径 r in [999, 1700]：
        目标函数：MoveCost(cur_pos -> q(r)) + ScanCost(q(r)) + ConnectCost(q(r) -> next_pos)
        原来的 r = 999.0 始终作为必选候选之一。
        """
        cur_p = np.array(self.cur_pos, dtype=float)
        next_p = np.array(next_pos, dtype=float) if next_pos is not None else None

        # 候选半径集合: 999.0 必须始终保留，配合步长 25m 离散采样点
        candidate_r = [999.0] + list(np.arange(1000.0, 1700.1, 25.0))

        # 预先获取当前所有 UNKNOWN 频道
        unknown_channels = [c for c, st in self.channels.items() if st.status == "UNKNOWN"]

        best_cost = 1e9
        best_r = 999.0
        best_details = {}
        cost_baseline = None

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        for r in candidate_r:
            q = (float(r * cos_t), float(r * sin_t))
            q_arr = np.array(q, dtype=float)

            # 1. 当前位置到检测点的位移费用 (速度 5.0m/s)
            d_cur = float(np.linalg.norm(q_arr - cur_p))
            t_move_cur = d_cur / 5.0

            # 2. 本站拟扫描费用
            channels_to_scan = []
            for ch in unknown_channels:
                if self.evidence_tracker.can_eliminate_any_cell(q, ch):
                    channels_to_scan.append(ch)

            if not channels_to_scan:
                t_scan = 0.0
            else:
                # 拟扫描规则完全同 scan_channels_at_station: 若当前频道在其中，则优先排第一以省一次切频
                if self.cur_channel in channels_to_scan:
                    channels_to_scan.remove(self.cur_channel)
                    channels_to_scan.insert(0, self.cur_channel)

                cur_ch = self.cur_channel
                t_scan = 0.0
                for ch in channels_to_scan:
                    if ch != cur_ch:
                        t_scan += 1.0
                        cur_ch = ch
                    t_scan += 5.0

            # 3. 衔接后续任务的移动费用 (没有后续任务时不附加返回原点费用)
            if next_p is not None:
                d_next = float(np.linalg.norm(next_p - q_arr))
                t_connect = d_next / 5.0
            else:
                t_connect = 0.0

            total_c = t_move_cur + t_scan + t_connect

            if abs(r - 999.0) < 1e-4:
                cost_baseline = total_c

            # 选优 (严格更优才替换，防止微小浮点误差扰动)
            if total_c < best_cost - 1e-4:
                best_cost = total_c
                best_r = r
                best_details = {
                    "move_cur_s": t_move_cur,
                    "scan_s": t_scan,
                    "connect_s": t_connect,
                    "channels_to_scan": channels_to_scan,
                }

        # 如果最优解与基线 999.0 费用几乎一致 (<= 1e-4)，保持基线 999.0
        if cost_baseline is not None and abs(best_cost - cost_baseline) <= 1e-4:
            best_r = 999.0
            best_cost = cost_baseline

        chosen_pt = (float(best_r * cos_t), float(best_r * sin_t))
        info = {
            "ray_idx": ray_idx,
            "theta_deg": math.degrees(theta),
            "chosen_r": best_r,
            "chosen_pos": chosen_pt,
            "best_cost": best_cost,
            "cost_baseline": cost_baseline,
            "expected_save_s": (cost_baseline - best_cost) if cost_baseline is not None else 0.0,
            "details": best_details,
        }
        return best_r, chosen_pt, info

    def run_version_c_openroute(self):
        """版本 C / C_openroute：开放路线重排 (Nearest Insertion + 2-Opt 启发式)"""
        ver_tag = "C_OPT" if self.enable_pruning else "C_BASELINE"
        self._log(f">>> 启动方案版本 {ver_tag} (开放路线重排 | 动态剪枝={self.enable_pruning}) <<<")

        # 1. 原点首扫
        self.scan_channels_at_station((0.0, 0.0))
        if self.enable_pruning:
            self.prune_redundant_search_points()

        while not self.check_completion():
            if self._check_budget_or_stop():
                break

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
                path = [0]
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
                start_i = -1 if self.enable_2opt_head else 0
                pre_2opt_head = path[0]  # 记录进入 2-opt 优化前的首任务
                while improved and opt_iter < 15:
                    improved = False
                    opt_iter += 1
                    for i in range(start_i, len(path) - 1):
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
                                path[i + 1 : j + 1] = list(reversed(path[i + 1 : j + 1]))
                                self.total_2opt_swaps += 1  # 内部交换次数另列
                                improved = True
                                break
                        if improved:
                            break

                final_head = path[0]  # 2-opt 优化后最终实际派发的首任务
                head_changed = (pre_2opt_head != final_head)
                if head_changed:
                    self.dispatched_head_change_count += 1
                    old_t_name = f"目标{tasks[pre_2opt_head]['channel']}" if tasks[pre_2opt_head]['type'] == 'target' else f"搜索点{tasks[pre_2opt_head]['point_idx']}"
                    new_t_name = f"目标{tasks[final_head]['channel']}" if tasks[final_head]['type'] == 'target' else f"搜索点{tasks[final_head]['point_idx']}"
                    self._log(f"【2-Opt最终派发首任务变更】由 {old_t_name} 变更为 {new_t_name}")

                # 【首任务派发审计】逐轮记录 2-opt 前后的首任务与实际派发任务，
                # 用于统计"真正改变了下一动作"的次数（区别于 total_2opt_swaps 的内部交换次数）
                self.head_dispatch_records.append({
                    "round": len(self.head_dispatch_records) + 1,
                    "virtual_time_s": round(self.virtual_time_s, 2),
                    "task_count": len(tasks),
                    "path_len": len(path),
                    "pre_head": describe_task(tasks[pre_2opt_head]),
                    "final_head": describe_task(tasks[final_head]),
                    "head_changed": head_changed,
                })

                best_task = tasks[path[0]]

            if best_task["type"] == "target":
                ch = best_task["channel"]
                d_est = np.linalg.norm(np.array(best_task["pos"]) - np.array(self.cur_pos))
                self._log(f"开放路线调度：选择任务链路首目标 {ch} (估计距离 {d_est:.1f}m)")
                self.service_found_target(ch)
            else:
                nom_pt = best_task["pos"]
                ang = math.atan2(nom_pt[1], nom_pt[0]) % (2.0 * math.pi)
                ray_idx = int(round(ang / (2.0 * math.pi / 7.0))) % 7
                theta = 2.0 * math.pi * ray_idx / 7.0

                if not self.is_p4 and self.enable_adaptive_radial_coverage:
                    next_pos = tasks[path[1]]["pos"] if len(path) > 1 else None
                    chosen_r, pt, r_info = self._select_radial_search_point(
                        ray_idx=ray_idx,
                        theta=theta,
                        nom_pt=nom_pt,
                        next_pos=next_pos,
                    )
                    if abs(chosen_r - 999.0) > 1e-3:
                        self.radial_adjustments_count += 1
                        self.radial_events.append({
                            "virtual_time_s": round(self.virtual_time_s, 2),
                            "ray_idx": ray_idx,
                            "theta_deg": round(math.degrees(theta), 2),
                            "nom_pos": (round(nom_pt[0], 2), round(nom_pt[1], 2)),
                            "chosen_r": round(chosen_r, 2),
                            "chosen_pos": (round(pt[0], 2), round(pt[1], 2)),
                            "cur_pos": (round(self.cur_pos[0], 2), round(self.cur_pos[1], 2)),
                            "next_pos": (round(next_pos[0], 2), round(next_pos[1], 2)) if next_pos else None,
                            "cost_baseline_s": round(r_info["cost_baseline"], 2) if r_info["cost_baseline"] is not None else None,
                            "cost_chosen_s": round(r_info["best_cost"], 2),
                            "expected_save_s": round(r_info["expected_save_s"], 2),
                        })
                        self._log(
                            f"【径向覆盖选点调整】射线 {ray_idx} (θ={math.degrees(theta):.1f}°): 基线 r=999.0m -> 选定 r={chosen_r:.1f}m "
                            f"(预计耗时 {r_info['cost_baseline']:.1f}s -> {r_info['best_cost']:.1f}s, 预期节省 {r_info['expected_save_s']:.1f}s)"
                        )
                else:
                    pt = nom_pt

                if nom_pt in self.remaining_search_points:
                    self.remaining_search_points.remove(nom_pt)
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
        enter_res = self.driver.enter() or {}
        # 现实/虚拟预算：以模拟器返回为准，缺失时退回赛题默认值
        self.max_virtual_duration_s = float(
            enter_res.get("max_virtual_duration_s",
                          enter_res.get("remaining_virtual_duration_s", 360000.0)) or 360000.0
        )
        self.max_real_duration_s = float(
            enter_res.get("max_real_duration_s",
                          enter_res.get("remaining_real_duration_s", 1200.0)) or 1200.0
        )

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
        absent_coverage_count = sum(
            1 for st in self.channels.values()
            if st.status == "ABSENT" and getattr(st, "absence_proof_type", None) == "COVERAGE_NEGATIVE"
        )
        absent_upper_bound_count = sum(
            1 for st in self.channels.values()
            if st.status == "ABSENT" and getattr(st, "absence_proof_type", None) == "UPPER_BOUND_EXCLUSION"
        )
        unsolved_count = sum(1 for st in self.channels.values() if st.status in ["UNKNOWN", "FOUND"])
        failed_count = sum(1 for st in self.channels.values() if st.status == "FAILED")
        real_time_s = self.end_real_time - self.start_real_time

        # 终止/完成状态：区分"成功完成"与"预算安全退出"，不伪造完成
        all_channels_ok = all(st.status in ("CLEARED", "ABSENT") for st in self.channels.values())
        if self.terminal_reason in ("VIRTUAL_BUDGET_EXHAUSTED", "REAL_BUDGET_EXHAUSTED"):
            self.completion_status = "SAFE_EXIT_BUDGET"
        elif all_channels_ok:
            self.completion_status = "COMPLETED"
        else:
            self.completion_status = "INCOMPLETE"

        summary = {
            "version": self.version,
            "is_p4": self.is_p4,
            "enable_pruning": self.enable_pruning,
            "scan_at_clearance": self.scan_at_clearance,
            "enable_2opt_head": self.enable_2opt_head,
            "enable_adaptive_radial_coverage": self.enable_adaptive_radial_coverage,
            "dispatched_head_change_count": self.dispatched_head_change_count,
            "total_2opt_swaps": self.total_2opt_swaps,
            "radial_adjustments_count": self.radial_adjustments_count,
            "radial_events": self.radial_events,
            "head_dispatch_records": self.head_dispatch_records,
            "head_dispatch_rounds": len(self.head_dispatch_records),
            "empty_prediction_count": getattr(self.local_decision, "empty_prediction_count", 0),
            "unrepresentable_prediction_count": getattr(self.local_decision, "unrepresentable_prediction_count", 0),
            "plan_uncovered_count": getattr(self.local_decision, "plan_uncovered_count", 0),
            "max_single_decision_ms": getattr(self.local_decision, "max_decision_real_time_ms", 0.0),
            "virtual_time_s": self.virtual_time_s,
            "real_time_s": real_time_s,
            "cleared_count": cleared_count,
            "absent_count": absent_count,
            "absent_coverage_count": absent_coverage_count,
            "absent_upper_bound_count": absent_upper_bound_count,
            "unsolved_count": unsolved_count,
            "failed_count": failed_count,
            "failed_targets": self.failed_targets,
            "completion_status": self.completion_status,
            "completed_successfully": self.completion_status == "COMPLETED",
            "terminal_reason": self.terminal_reason,
            "max_virtual_duration_s": self.max_virtual_duration_s,
            "max_real_duration_s": self.max_real_duration_s,
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
