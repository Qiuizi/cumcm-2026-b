"""
local_decision.py - 方案第 5 节：闭环单目标局部决策器 (严格信息隔离与闭环评分)
实现：
1. 几何硬过滤：min_{z in Z_j} ||q - z|| > 1500 + sqrt(2) 必然无信号直接舍弃
2. 候选生成：顺路点、接近点、侧向点，补充从历史阳性点侧接近选项
3. 闭环场景预测与成本评分：
   - 假想场景采样 -> 预测三类实际物理反馈 (near / direction / no_signal)
   - 测后可行域模拟更新 (P4 模式无信号保持网格不裁剪，严格承认无信号代价)
   - 实际清除序列生成与真实时钟累计 (移动 + 切频 1s + 测量 5s + 失败清除 3s + 成功清除 5s)
   - 严格遵守信息隔离：场景真坐标绝不直接选点或提供捷径
4. 门槛比较与停止规则：仅当 min J(q) + margin < J0 且未达上限时补测，否则提交清除计划
5. 详细审计信息：在决策字典中输出 J0、J(q)、预测反馈与存活单元数
"""

import time
import math
import numpy as np
from src.conservative_grid import ConservativeGrid


class LocalDecisionMaker:
    def __init__(
        self,
        max_followups: int = 12,
        max_followup_time_s: float = 600.0,
        margin_s: float = 5.0,
        max_dist_from_origin: float = 5000.0,
    ):
        self.max_followups = max_followups
        self.max_followup_time_s = max_followup_time_s
        self.margin_s = margin_s
        self.max_dist_from_origin = max_dist_from_origin

        # 异常计数与现实性能监控指标
        self.empty_prediction_count = 0      # 预测网格出现空集的次数
        self.plan_uncovered_count = 0        # 覆盖计划未命中某样本场景的次数
        self.max_decision_real_time_ms = 0.0 # 单次决策最大现实耗时 (ms)

    def generate_candidates(
        self,
        cur_p: tuple,
        grid: ConservativeGrid,
        anchor_a: tuple = None,
        measured_positions: list = None,
        p1: tuple = None,
    ):
        """
        生成候选补测位置 (方案第 5.2 节增强版)
        含几何硬过滤与历史阳性点侧接近
        """
        if measured_positions is None:
            measured_positions = []

        cur = np.array(cur_p, dtype=float)
        mu, u_major, L = grid.get_bounding_features()
        d_mu = float(np.linalg.norm(mu - cur))

        # 确保 u_major 朝向 mu 方向
        if np.dot(u_major, mu - cur) < 0:
            u_major = -u_major
        v_major = np.array([-u_major[1], u_major[0]])

        candidates = []

        # 1. 当前点 (若未测过)
        candidates.append(cur)

        # 2. 顺路点 (若有锚点 a)
        if anchor_a is not None:
            anc = np.array(anchor_a, dtype=float)
            for frac in [0.25, 0.5, 0.75, 1.0]:
                candidates.append(cur + frac * (anc - cur))

        # 3. 接近点 (沿 cur -> mu 前进)
        if d_mu > 1e-3:
            dir_to_mu = (mu - cur) / d_mu
            for step in [100.0, 300.0, 600.0]:
                if step < d_mu:
                    candidates.append(cur + step * dir_to_mu)
                else:
                    candidates.append(mu)

        # 4. 侧向点 (mu - 0.25*L*u_major +- b*v_major)
        base_lateral = mu - 0.25 * L * u_major
        b_choices = [
            min(0.1 * L, 50.0),
            min(0.25 * L, 150.0),
            min(0.5 * L, 300.0),
        ]
        for b_val in b_choices:
            if b_val > 5.0:
                candidates.append(base_lateral + b_val * v_major)
                candidates.append(base_lateral - b_val * v_major)

        # 5. 近处小侧移 (mu +- min(0.1*L, 20)*v_major)
        b_small = min(0.1 * L, 20.0)
        if b_small > 5.0:
            candidates.append(mu + b_small * v_major)
            candidates.append(mu - b_small * v_major)

        # 6. 区域中心 mu
        candidates.append(mu)

        # 7. 历史阳性点侧接近 (从历史正信号侧切入，赋予折返至正面信号侧的能力)
        pos_origin = p1 if p1 is not None else (grid.p1 if hasattr(grid, "p1") else None)
        if pos_origin is not None:
            p_orig = np.array(pos_origin, dtype=float)
            candidates.append(p_orig)
            for alpha in [0.25, 0.5, 0.75]:
                candidates.append(p_orig + alpha * (mu - p_orig))

        # 过滤与去重
        cells = grid.get_surviving_cells()
        filtered = []
        seen = set()

        for c in candidates:
            c_arr = np.array(c, dtype=float)
            # 限制坐标在 5000m 圆内
            if np.linalg.norm(c_arr) > self.max_dist_from_origin:
                continue

            # 必然无信号的几何硬过滤：min_{z in Z_j} ||q - z|| > 1500 + d_g 必然无信号
            if len(cells) > 0:
                dists_to_cells = np.linalg.norm(cells - c_arr[None, :], axis=1)
                if np.min(dists_to_cells) > 1500.0 + grid.d_g:
                    continue

            # 四舍五入到 0.5 米去重
            key = (round(float(c_arr[0]), 1), round(float(c_arr[1]), 1))
            if key in seen:
                continue

            # 排除与已测位置重合 (<= 2m)
            too_close = False
            for mp in measured_positions:
                if np.linalg.norm(c_arr - np.array(mp)) <= 2.0:
                    too_close = True
                    break
            if too_close:
                continue

            seen.add(key)
            filtered.append((float(c_arr[0]), float(c_arr[1])))
            if len(filtered) >= 20:
                break

        return filtered

    def _eval_plan_on_scenarios(self, start_p, plan, scenarios, infeasible_penalty_s: float = 1e9):
        """
        物理时钟闭环模拟：
        从 start_p 开始依次执行 plan，直到场景真坐标 sc 进入 20m 清除半径。
        返回在各场景下累计物理耗时的期望值。
        【严格信息隔离与不可行判决】：
        真坐标 sc 仅用于判断 plan 某步是否命中 (<= 20m)；
        若计划未能覆盖命中样本，严禁瞬移至 sc，直接记录未覆盖次数并赋以不可行人为惩罚 (1e9)，
        判该候选点无法闭环覆盖，不可冒充可执行兜底时间。
        """
        if len(scenarios) == 0:
            return 0.0
        if len(plan) == 0:
            self.plan_uncovered_count += len(scenarios)
            return infeasible_penalty_s

        costs = []
        start_arr = np.array(start_p, dtype=float)

        for sc in scenarios:
            t = 0.0
            last = start_arr
            cleared = False
            for cp in plan:
                cp_arr = np.array(cp, dtype=float)
                d = np.linalg.norm(cp_arr - last)
                t += d / 5.0
                last = cp_arr
                if np.linalg.norm(sc - cp_arr) <= 20.0:
                    t += 5.0  # 成功清除耗时 5s
                    cleared = True
                    break
                else:
                    t += 3.0  # 失败清除耗时 3s
            if not cleared:
                # 计划遍历完仍未命中：记录未覆盖次数，施加不可行标记
                self.plan_uncovered_count += 1
                t += infeasible_penalty_s
            costs.append(t)

        return float(np.mean(costs))

    def decide_action(self, *args, **kwargs):
        """包装单次决策耗时监控"""
        t0 = time.perf_counter()
        res = self._decide_action_impl(*args, **kwargs)
        t_ms = (time.perf_counter() - t0) * 1000.0
        if t_ms > self.max_decision_real_time_ms:
            self.max_decision_real_time_ms = t_ms
        res["decision_real_time_ms"] = round(t_ms, 2)
        return res

    def _decide_action_impl(
        self,
        cur_p: tuple,
        channel: int,
        grid: ConservativeGrid,
        followup_count: int,
        followup_time_s: float,
        force_clear: bool,
        anchor_a: tuple = None,
        measured_positions: list = None,
        cur_channel: int = None,
        is_p4: bool = False,
        p1: tuple = None,
    ):
        """
        决定下一动作 (闭环真实代价评估):
        返回包含 J0、J(q)、预测反馈及选点依据的结构化字典
        """
        if cur_channel is None:
            cur_channel = channel

        # 1. 检查是否满足安全清除条件
        safe_pos = grid.find_safe_clear_position(cur_p)
        if safe_pos is not None:
            return {
                "action_type": "clear",
                "position": safe_pos,
                "reason": "safe_clear_guaranteed",
                "force_clear": True,
                "clear_plan": [safe_pos],
                "j0": 5.0,
                "best_jq": 1e9,
                "predicted_feedback": "safe_near",
                "surviving_cells": grid.count(),
            }

        # 始终准备有限清除计划
        clear_plan = grid.build_clear_plan(cur_p, anchor_a)

        # 2. 检查硬性停止条件
        if force_clear:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": "force_clear_mode",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": 0.0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": grid.count(),
            }

        if followup_count >= self.max_followups:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": "max_followups_reached",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": 0.0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": grid.count(),
            }

        if followup_time_s >= self.max_followup_time_s:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": "max_followup_time_reached",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": 0.0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": grid.count(),
            }

        surviving = grid.get_surviving_cells()
        if len(surviving) == 0:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": "empty_grid_fallback",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": 0.0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": 0,
            }

        # 3. 抽样场景并评估当前网格直接清除基准成本 J0
        # 选取最多 10 个代表性样本点作为预测场景
        K = min(10, len(surviving))
        idx_sample = np.linspace(0, len(surviving) - 1, K, dtype=int)
        scenarios = surviving[idx_sample]

        j0 = self._eval_plan_on_scenarios(cur_p, clear_plan, scenarios)

        # 若清除计划仅需 1 步即可覆盖，直接清除最稳健划算
        if len(clear_plan) <= 1:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": "short_clear_plan",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": j0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": len(surviving),
            }

        # 4. 生成候选点并进行闭环场景预测与测后清除成本评估
        p1_pos = p1 if p1 is not None else (grid.p1 if hasattr(grid, "p1") else None)
        candidates = self.generate_candidates(
            cur_p, grid, anchor_a, measured_positions, p1=p1_pos
        )

        if not candidates:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": "no_valid_candidates",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": j0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": len(surviving),
            }

        best_q = None
        best_jq = 1e9
        best_feedback_summary = "none"

        cur_arr = np.array(cur_p, dtype=float)
        p1_arr = np.array(p1_pos, dtype=float) if p1_pos is not None else None

        for q in candidates:
            q_arr = np.array(q, dtype=float)
            dist_to_q = float(np.linalg.norm(q_arr - cur_arr))
            # 基础耗时：移动 + 切频道 (若切换 +1s) + 检测 5s
            t_switch = 1.0 if channel != cur_channel else 0.0
            t_base = dist_to_q / 5.0 + t_switch + 5.0
            # 惰性评估变量：仅在实际存在正概率 no_signal 分支时才进行网格裁剪与清除计划构建
            plan_nosig = None
            nosig_evaluated = False
            nosig_is_empty = False

            sc_costs = []
            feedbacks = []
            cand_infeasible = False

            for sc in scenarios:
                d_sc = float(np.linalg.norm(q_arr - sc))

                # 反馈类型判定
                if d_sc <= 5.0:
                    # 1. near 反馈：在 q 原地清除 5s 即可
                    sc_costs.append(t_base + 5.0)
                    feedbacks.append("near")
                    continue

                # 判定是否能收到有效测向信号 (基于距离与定向波束模型)
                if d_sc > 1500.0:
                    p_recv = 0.0
                elif d_sc > 1000.0:
                    p_recv = (1500.0 - d_sc) / 500.0
                else:
                    p_recv = 1.0

                if is_p4 and p1_arr is not None:
                    # 定向源模型：源在首测点 p1 被发现，说明发射方向朝向 p1
                    v_p1 = p1_arr - sc
                    v_q = q_arr - sc
                    norm_p1 = np.linalg.norm(v_p1)
                    norm_q = np.linalg.norm(v_q)
                    if norm_p1 > 1e-3 and norm_q > 1e-3:
                        cos_psi = np.clip(np.dot(v_p1, v_q) / (norm_p1 * norm_q), -1.0, 1.0)
                        psi = math.acos(cos_psi)  # 偏角 [0, pi]
                        p_beam = max(0.0, 1.0 - psi / math.pi)
                    else:
                        p_beam = 1.0
                    # 50% 全向源，50% 定向源
                    p_recv *= (0.5 + 0.5 * p_beam)

                p_nosig = 1.0 - p_recv

                # 情形 A 耗时 (no_signal 分支：仅在正概率时惰性评估，零概率分支直接跳过)
                if p_nosig > 0.0:
                    if not nosig_evaluated:
                        nosig_evaluated = True
                        grid_nosig = grid.clone()
                        if not is_p4:
                            grid_nosig.prune_by_no_signal_omni(tuple(q_arr))
                        if grid_nosig.count() > 0:
                            plan_nosig = grid_nosig.build_clear_plan(tuple(q_arr), anchor_a)
                        else:
                            # 仅在正概率实际生效时，才记录有效预测空集异常并显式标记不可行
                            self.empty_prediction_count += 1
                            nosig_is_empty = True
                            plan_nosig = []

                    if nosig_is_empty or len(plan_nosig) == 0:
                        cand_infeasible = True
                        cost_nosig = t_base + 1e9
                    else:
                        cost_nosig = t_base + self._eval_plan_on_scenarios(q_arr, plan_nosig, [sc])
                else:
                    cost_nosig = 0.0

                # 情形 B: direction 反馈 (仅在正概率时评估)
                # 使用网格克隆副本，统一调用真实 prune_by_direction 与 build_clear_plan，杜绝信息捷径
                if p_recv > 0.0:
                    th_deg = math.degrees(math.atan2(sc[1] - q_arr[1], sc[0] - q_arr[0])) % 360.0
                    grid_dir = grid.clone()
                    grid_dir.prune_by_direction(tuple(q_arr), th_deg)
                    if grid_dir.count() > 0:
                        plan_dir = grid_dir.build_clear_plan(tuple(q_arr), anchor_a)
                        cost_dir = t_base + self._eval_plan_on_scenarios(q_arr, plan_dir, [sc])
                    else:
                        # 正概率下合法测向排掉生成它的样本：记录有效异常并显式标记不可行
                        self.empty_prediction_count += 1
                        cand_infeasible = True
                        cost_dir = t_base + 1e9
                else:
                    cost_dir = 0.0

                expected_sc_cost = p_recv * cost_dir + p_nosig * cost_nosig
                sc_costs.append(expected_sc_cost)
                feedbacks.append("dir" if p_recv >= 0.5 else "no_sig")

            total_jq = float(np.mean(sc_costs))
            if total_jq < best_jq:
                best_jq = total_jq
                best_q = q
                best_feedback_summary = f"dir({feedbacks.count('dir')})/no_sig({feedbacks.count('no_sig')})/near({feedbacks.count('near')})"

        # 5. 门槛判决: 仅当 min J(q) + margin_s < J0 时补测
        if best_q is not None and best_jq + self.margin_s < j0:
            return {
                "action_type": "measure",
                "position": best_q,
                "reason": f"followup_promising (Jq={best_jq:.1f}s vs J0={j0:.1f}s)",
                "force_clear": False,
                "clear_plan": clear_plan,
                "j0": j0,
                "best_jq": best_jq,
                "predicted_feedback": best_feedback_summary,
                "surviving_cells": len(surviving),
            }
        else:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": f"direct_clear_better (J0={j0:.1f}s vs Jq={best_jq:.1f}s)",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": j0,
                "best_jq": best_jq,
                "predicted_feedback": best_feedback_summary,
                "surviving_cells": len(surviving),
            }
