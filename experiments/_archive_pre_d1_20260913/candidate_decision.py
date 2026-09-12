"""
candidate_decision.py —— P4 历史接收模型候选版（正式候选实现）

!! 本文件由 tools/build_candidate_method.py 在**构建期**生成，请勿手工编辑 !!
   （生成规则：读取冻结版 decide_action 源码，仅替换"接收概率"一个切片，其余逐字保留）

与冻结基线的唯一差异
--------------------------------------------------
`decide_action` 中的接收概率改由显式接口 `self._reception_probability(...)` 决定。
该接口内部：
  - 优先使用 `self.predictor`（满足 ReceptionPredictor 协议的历史接收模型）；
  - 模型不可用（假设集耗尽 / 未接入）时，**逐字回退**冻结公式 `frozen_recv_prob`，
    并记录原因与次数。

运行期不读取、不 exec 任何外部源码；本文件是普通 Python 模块。
"""
from __future__ import annotations

import math

import numpy as np

from conservative_grid_frozen import ConservativeGrid
from local_decision_frozen import LocalDecisionMaker as FrozenDecisionMaker

# 标记：候选版唯一改动的边界（verify_equivalence.py 依赖这两个字符串）
CANDIDATE_BEGIN = "# ===== HISTORY-CANDIDATE 唯一改动（开始）====="
CANDIDATE_END = "# ===== HISTORY-CANDIDATE 唯一改动（结束）====="


def frozen_recv_prob(d_sc, sc, q_arr, p1_arr, is_p4):
    """
    冻结版接收概率公式的**逐字复刻**，仅在候选版回退时使用，
    保证"回退 == 稳定基线行为"。
    """
    if d_sc > 1500.0:
        p_recv = 0.0
    elif d_sc > 1000.0:
        p_recv = (1500.0 - d_sc) / 500.0
    else:
        p_recv = 1.0

    if is_p4 and p1_arr is not None:
        v_p1 = p1_arr - sc
        v_q = q_arr - sc
        norm_p1 = np.linalg.norm(v_p1)
        norm_q = np.linalg.norm(v_q)
        if norm_p1 > 1e-3 and norm_q > 1e-3:
            cos_psi = np.clip(np.dot(v_p1, v_q) / (norm_p1 * norm_q), -1.0, 1.0)
            psi = math.acos(cos_psi)
            p_beam = max(0.0, 1.0 - psi / math.pi)
        else:
            p_beam = 1.0
        p_recv *= (0.5 + 0.5 * p_beam)
    return p_recv


class HistoryCandidateDecision(FrozenDecisionMaker):
    """
    候选版决策器：基类 = 冻结决策器；只把接收概率交给 `self.predictor`。

    predictor 需满足 ReceptionPredictor 协议（见 predictor.py）：
        prepare_for_decision(channel, grid) -> dict
        reception_probability(q) -> float | None
    未传 predictor 时全部走冻结回退，即与稳定基线逐字等价。
    """

    def __init__(self, predictor=None, record_baseline_comparison: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.predictor = predictor
        self.record_baseline_comparison = bool(record_baseline_comparison)

        self.model_score_count = 0
        self.call_fallback_count = 0
        self.decision_with_model_count = 0
        self.decision_fallback_count = 0
        self.fallback_reason_hist = {}
        self.action_changed_count = 0
        self.position_changed_count = 0
        self.decision_records = []

    # ---------------- 显式接收预测接口的调用点（含安全回退） ----------------
    def _reception_probability(self, channel, grid, q_arr, d_sc, sc, p1_arr, is_p4):
        """
        候选版唯一改动点的落地实现。

        首次进入某个频道的候选评分时，先让 predictor 用**该时刻的历史观测**建立假设集；
        此后每次决策按观测条数增量更新。模型不可用时逐字回退冻结公式（安全回退）。
        """
        if self.predictor is None:
            self.call_fallback_count += 1
            self.fallback_reason_hist["predictor_not_attached"] = (
                self.fallback_reason_hist.get("predictor_not_attached", 0) + 1)
            return frozen_recv_prob(d_sc, sc, q_arr, p1_arr, is_p4)

        prep = self.predictor.prepare_for_decision(channel=channel, grid=grid)
        _ = prep  # 仅用于建立/更新假设集；决策级计数在包装器中按"是否真的调用过模型"统计

        p = self.predictor.reception_probability(q_arr)
        if p is None:
            reason = self.predictor.last_unavailable_reason or "model_unavailable"
            self.call_fallback_count += 1
            self.fallback_reason_hist[reason] = self.fallback_reason_hist.get(reason, 0) + 1
            return frozen_recv_prob(d_sc, sc, q_arr, p1_arr, is_p4)

        self.model_score_count += 1
        return p


    def _decide_with_history(
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
                "best_jq": None,
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
                "best_jq": None,
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
                "best_jq": None,
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
                "best_jq": None,
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
                "best_jq": None,
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
                "best_jq": None,
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
                "best_jq": None,
                "predicted_feedback": "none",
                "surviving_cells": 0,
            }

        # 3. 抽样场景并评估当前网格直接清除基准成本 J0
        # 选取最多 10 个代表性样本点作为预测场景
        K = min(10, len(surviving))
        idx_sample = np.linspace(0, len(surviving) - 1, K, dtype=int)
        scenarios = surviving[idx_sample]

        # J0 = 按当前清除计划（就是执行侧会用的同一条计划）逐场景累计的实际成本；
        # 若计划无法覆盖某场景，则 J0 不可表示，此时不做补测评估，直接执行清除。
        j0_costs, j0_ok = self._eval_plan_on_scenarios(cur_p, clear_plan, scenarios)
        j0 = float(np.mean(j0_costs)) if j0_ok and j0_costs else 0.0

        # 若清除计划仅需 1 步即可覆盖，直接清除最稳健划算
        if len(clear_plan) <= 1:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": "short_clear_plan",
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": j0,
                "best_jq": None,
                "predicted_feedback": "none",
                "surviving_cells": len(surviving),
            }

        # 4. 生成候选点并进行闭环场景预测与测后清除成本评估
        p1_pos = p1 if p1 is not None else (grid.p1 if hasattr(grid, "p1") else None)
        candidates = self.generate_candidates(
            cur_p, grid, anchor_a, measured_positions, p1=p1_pos
        )

        if not candidates or not j0_ok:
            return {
                "action_type": "clear",
                "position": clear_plan[0],
                "reason": ("no_valid_candidates" if not candidates else "j0_unrepresentable_direct_clear"),
                "force_clear": True,
                "clear_plan": clear_plan,
                "j0": j0,
                "best_jq": None,
                "predicted_feedback": "none",
                "surviving_cells": len(surviving),
            }

        best_q = None
        best_jq = None
        best_feedback_summary = "none"

        cur_arr = np.array(cur_p, dtype=float)
        p1_arr = np.array(p1_pos, dtype=float) if p1_pos is not None else None

        for q in candidates:
            q_arr = np.array(q, dtype=float)
            dist_to_q = float(np.linalg.norm(q_arr - cur_arr))
            # 基础耗时：移动 + 切频道 (若切换 +1s) + 检测 5s
            t_switch = 1.0 if channel != cur_channel else 0.0
            t_base = dist_to_q / 5.0 + t_switch + 5.0

            sc_costs = []
            feedbacks = []
            cand_representable = True
            plan_nosig = None

            for sc in scenarios:
                d_sc = float(np.linalg.norm(q_arr - sc))

                # 1. near 反馈：在 q 原地清除 5s 即可（无需网格）
                if d_sc <= 5.0:
                    sc_costs.append(t_base + 5.0)
                    feedbacks.append("near")
                    continue

                # ===== HISTORY-CANDIDATE 唯一改动（开始）=====
                p_recv = self._reception_probability(
                    channel=channel, grid=grid, q_arr=q_arr, d_sc=d_sc, sc=sc,
                    p1_arr=p1_arr, is_p4=is_p4)
                # ===== HISTORY-CANDIDATE 唯一改动（结束）=====
                p_nosig = 1.0 - p_recv

                # ---- 情形 A: no_signal 反馈（仅在正概率时评估）----
                # P4 语义：定向源可能静默，网格不收缩；因此这里用的就是执行侧同一条
                # 计划生成器 grid.build_clear_plan，不存在任何"额外知道的位置"。
                if p_nosig > 0.0:
                    if plan_nosig is None:
                        plan_nosig = grid.build_clear_plan(tuple(q_arr), anchor_a)
                    costs, ok = self._eval_plan_on_scenarios(q_arr, plan_nosig, [sc])
                    if not ok:
                        self.unrepresentable_prediction_count += 1
                        cand_representable = False
                        break
                    cost_nosig = t_base + costs[0]
                else:
                    cost_nosig = 0.0

                # ---- 情形 B: direction 反馈（仅在正概率时评估）----
                # 【修复·缺陷1】克隆真实网格并复用真实观测更新函数 prune_by_direction，
                # 删除重复手写的角域判据（其不等号方向是反的）。
                # 克隆操作保证预测不修改原网格。
                if p_recv > 0.0:
                    th_deg = math.degrees(math.atan2(sc[1] - q_arr[1], sc[0] - q_arr[0])) % 360.0
                    grid_dir = grid.clone()
                    grid_dir.prune_by_direction(tuple(q_arr), th_deg)
                    if grid_dir.count() == 0 or getattr(grid_dir, "contradiction", False):
                        # 正概率下合法测向把生成它的样本排空 => 模型矛盾，显式记为不可表示
                        self.unrepresentable_prediction_count += 1
                        self.empty_prediction_count += 1
                        cand_representable = False
                        break
                    # 【修复·缺陷2】用同一个计划生成器，而不是 plan_dir=[sc] 或"剪枝后均值点"
                    plan_dir = grid_dir.build_clear_plan(tuple(q_arr), anchor_a)
                    costs, ok = self._eval_plan_on_scenarios(q_arr, plan_dir, [sc])
                    if not ok:
                        self.unrepresentable_prediction_count += 1
                        cand_representable = False
                        break
                    cost_dir = t_base + costs[0]
                else:
                    cost_dir = 0.0

                sc_costs.append(p_recv * cost_dir + p_nosig * cost_nosig)
                feedbacks.append("dir" if p_recv >= 0.5 else "no_sig")

            # 不可表示的候选不参与 argmin（既不注入惩罚，也不静默当作 0）
            if not cand_representable or not sc_costs:
                continue

            total_jq = float(np.mean(sc_costs))
            if best_jq is None or total_jq < best_jq:
                best_jq = total_jq
                best_q = q
                best_feedback_summary = f"dir({feedbacks.count('dir')})/no_sig({feedbacks.count('no_sig')})/near({feedbacks.count('near')})"

        # 5. 门槛判决: 仅当 min J(q) + margin_s < J0 时补测
        if best_q is not None and best_jq is not None and best_jq + self.margin_s < j0:
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

    # ---------------- 对外入口：只做诊断包装，不改变决策 ----------------
    def decide_action(self, cur_p, channel, grid, followup_count, followup_time_s,
                      force_clear, anchor_a=None, measured_positions=None,
                      cur_channel=None, is_p4=False, p1=None):
        """
        包装 `_decide_with_history`：
          - 先用**冻结基类在同一状态上**算一次对照决策（只读，用于统计"实际改变了什么"）；
          - 再执行候选决策；
          - 记录诊断。
        包装本身不改变任何决策输入；`record_baseline_comparison=False` 时跳过对照计算。
        """
        base = None
        if self.record_baseline_comparison:
            snap = (self.empty_prediction_count, self.unrepresentable_prediction_count,
                    getattr(self, "plan_uncovered_count", 0))
            base = FrozenDecisionMaker.decide_action(
                self, cur_p=cur_p, channel=channel, grid=grid,
                followup_count=followup_count, followup_time_s=followup_time_s,
                force_clear=force_clear, anchor_a=anchor_a,
                measured_positions=measured_positions, cur_channel=cur_channel,
                is_p4=is_p4, p1=p1)
            self.empty_prediction_count, self.unrepresentable_prediction_count = snap[:2]
            if hasattr(self, "plan_uncovered_count"):
                self.plan_uncovered_count = snap[2]

        before_calls = self.model_score_count + self.call_fallback_count
        res = self._decide_with_history(
            cur_p=cur_p, channel=channel, grid=grid,
            followup_count=followup_count, followup_time_s=followup_time_s,
            force_clear=force_clear, anchor_a=anchor_a,
            measured_positions=measured_positions, cur_channel=cur_channel,
            is_p4=is_p4, p1=p1)

        # 决策级计数：本次决策是否真的调用过模型、以及调用时模型是否可用
        if (self.model_score_count + self.call_fallback_count) > before_calls:
            if self.predictor is not None and self.predictor.last_usable:
                self.decision_with_model_count += 1
            else:
                self.decision_fallback_count += 1

        if base is not None:
            same_action = (base["action_type"] == res["action_type"])
            same_pos = (tuple(np.round(np.asarray(base["position"], dtype=float), 2))
                        == tuple(np.round(np.asarray(res["position"], dtype=float), 2)))
            if not same_action:
                self.action_changed_count += 1
            elif not same_pos:
                self.position_changed_count += 1
            self.decision_records.append({
                "channel": int(channel),
                "grid_count": int(grid.count()),
                "baseline_action": base["action_type"],
                "baseline_pos": [round(float(x), 2)
                                 for x in np.asarray(base["position"], dtype=float)],
                "baseline_j0": base.get("j0"), "baseline_jq": base.get("best_jq"),
                "candidate_action": res["action_type"],
                "candidate_pos": [round(float(x), 2)
                                  for x in np.asarray(res["position"], dtype=float)],
                "candidate_j0": res.get("j0"), "candidate_jq": res.get("best_jq"),
                "action_changed": (not same_action),
                "position_changed": (same_action and not same_pos),
                "model_alive": (self.predictor.last_n_alive
                                if self.predictor is not None else None),
                "model_n_obs": (self.predictor.last_n_obs
                                if self.predictor is not None else None),
                "model_usable": (self.predictor.last_usable
                                 if self.predictor is not None else None),
            })
        return res

    # ---------------- 审计 ----------------
    def audit(self) -> dict:
        return {
            "decision_with_model_count": self.decision_with_model_count,
            "decision_fallback_count": self.decision_fallback_count,
            "call_fallback_count": self.call_fallback_count,
            "model_score_count": self.model_score_count,
            "fallback_reason_hist": self.fallback_reason_hist,
            "action_changed_count": self.action_changed_count,
            "position_changed_count": self.position_changed_count,
            "decision_records": self.decision_records,
        }
