"""
local_decision.py - 方案第 5 节：闭环单目标局部决策器 (v3.3-scan-off-frozen 原样审查副本)
"""

import math
import numpy as np
from conservative_grid_frozen import ConservativeGrid


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

    @staticmethod
    def _eval_plan_on_scenarios(start_p, plan, scenarios):
        """
        物理时钟闭环模拟：
        从 start_p 开始依次执行 plan，直到场景真坐标 sc 进入 20m 清除半径。
        返回在各场景下累计物理耗时的期望值。
        """
        if len(scenarios) == 0 or len(plan) == 0:
            return 0.0

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
                # 计划遍历完未命中：补上移动至真实目标与兜底惩罚
                t += np.linalg.norm(sc - last) / 5.0 + 5.0 + 15.0
            costs.append(t)

        return float(np.mean(costs))

    def decide_action(
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

        # 0. 【修复】空网格 / 模型矛盾：显式判失败，绝不伪造"可安全清除"
        #    旧实现会经 check_safe_clear_at(空集)=True 走到 reason='safe_clear_guaranteed'，
        #    在固定位置无限重试同一失败清除；这里改为返回 fail 动作，交由引擎显式标记失败，
        #    既不解释为"目标不存在/已清除"，也不伪造完成。
        if grid.count() == 0 or getattr(grid, "contradiction", False):
            reason = ("empty_grid_no_valid_state" if grid.count() == 0
                      else "model_contradiction_observation_conflicts_with_grid")
            return {
                "action_type": "fail",
                "position": tuple(cur_p),
                "reason": reason,
                "force_clear": False,
                "clear_plan": [],
                "j0": 0.0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": int(grid.count()),
            }

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

        # 1b. 【修复】无合法清除计划时显式判失败，不用 clear_plan[0] 制造假动作
        if not clear_plan:
            return {
                "action_type": "fail",
                "position": tuple(cur_p),
                "reason": "no_valid_clear_plan",
                "force_clear": False,
                "clear_plan": [],
                "j0": 0.0,
                "best_jq": 1e9,
                "predicted_feedback": "none",
                "surviving_cells": int(grid.count()),
            }

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
            # 情形 A: no_signal 反馈 (概率 1 - p_recv)
            # 在 P4 下网格不收缩，机器狗以 q 为起点按原网格执行清除计划 (只需计算一次)
            plan_nosig = grid.build_clear_plan(tuple(q_arr), anchor_a)

            sc_costs = []
            feedbacks = []

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

                # 情形 A 耗时
                cost_nosig = t_base + self._eval_plan_on_scenarios(q_arr, plan_nosig, [sc])

                # 情形 B: direction 反馈 (概率 p_recv)
                # 预测测向度并虚拟剪枝
                th_deg = math.degrees(math.atan2(sc[1] - q_arr[1], sc[0] - q_arr[0])) % 360.0
                th_rad = math.radians(th_deg)
                eps_rad = math.radians(1.005)
                rel = surviving - q_arr[None, :]
                dists = np.linalg.norm(rel, axis=1)
                th_min = th_rad - eps_rad
                th_max = th_rad + eps_rad
                n_cw = np.array([math.sin(th_min), -math.cos(th_min)])
                n_ccw = np.array([-math.sin(th_max), math.cos(th_max)])
                mask = (
                    (np.dot(rel, n_cw) >= -grid.d_g)
                    & (np.dot(rel, n_ccw) >= -grid.d_g)
                    & (dists <= 1500.0 + grid.d_g)
                )
                pruned = surviving[mask]

                if len(pruned) == 0:
                    plan_dir = [tuple(sc)]
                else:
                    mu_pruned = np.mean(pruned, axis=0)
                    plan_dir = [(float(mu_pruned[0]), float(mu_pruned[1]))]

                cost_dir = t_base + self._eval_plan_on_scenarios(q_arr, plan_dir, [sc])

                expected_sc_cost = p_recv * cost_dir + (1.0 - p_recv) * cost_nosig
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
