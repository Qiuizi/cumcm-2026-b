"""
arm_decision.py —— 阶段2 的三个实验臂（A 基线 / B k=1 止损 / C 历史观测接收预测）

基线契约（见 BASELINE_CONTRACT.md）
--------------------------------------------------
P4 的真实基线是：
  驱动 src/sim_env.py
  引擎 src/strategy_engine.py  version="C" -> run_version_c_openroute
  冻结组件 local_decision_frozen.LocalDecisionMaker + conservative_grid_frozen.ConservativeGrid
  覆盖/证据 src/evidence_tracker.py (EvidenceTrackerP4)
因此臂 B 与臂 C **都必须以 local_decision_frozen.LocalDecisionMaker 为基类**，
否则测到的差异里会混入"冻结版 vs 共享版"的组件差异（两者相差 114 行）。

臂 A：直接使用冻结决策器，不做任何替换。
臂 B：`K1StopFrozenDecision`，只加"连续 1 次盲测即强制清除"，其余逐字继承冻结逻辑。
臂 C：`CHypothesisDecision`，只把**接收概率**换成历史观测假设模型的预测，其余逐字继承冻结逻辑；
      不叠加 k 规则。假设集全部不相容时回退到冻结公式，并记录原因与次数。

臂 C 的"逐字继承"是可机检的：
  `_decide_with_model` 的源码除掉被标记的替换块之后，必须与冻结版 `decide_action`
  除掉原接收概率块之后的源码逐行相同（见 check_mechanism.py 的源码一致性检查）。
"""

from __future__ import annotations

import inspect
import math
import os
import sys
import textwrap

import numpy as np

import local_decision_frozen
from conservative_grid_frozen import ConservativeGrid
from local_decision_frozen import LocalDecisionMaker as FrozenDecisionMaker

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from reception_model import ReceptionHypothesisModel  # noqa: E402

# 基线契约锁：本阶段记录的 local_decision_frozen.py 的 sha256 前缀。
# 若冻结源码被改动，臂 B / 臂 C 的"逐字继承"前提就不再成立，必须重新取证。
BASELINE_FROZEN_LOCAL_DECISION_SHA256_PREFIX = "6D26E61DE9A25FD4"


def build_decide_with_model():
    """
    由冻结源码程序化生成臂 C 的决策主体：
    读取 `LocalDecisionMaker.decide_action` 的源码，只把"接收概率"那一个切片
    替换成对假设模型的调用，其余逐字保留（含全部注释与空行）。
    返回 (方法对象, 生成后的源码文本)。
    """
    lines = inspect.getsource(FrozenDecisionMaker.decide_action).splitlines()
    s = next(i for i, ln in enumerate(lines) if "判定是否能收到有效测向信号" in ln)
    e = next(i for i, ln in enumerate(lines[s:], start=s)
             if "p_nosig = 1.0 - p_recv" in ln)
    indent = lines[s][:len(lines[s]) - len(lines[s].lstrip())]
    repl = [
        indent + ARM_C_BEGIN,
        indent + "p_recv = self._recv_prob_or_fallback(",
        indent + "    channel=channel, q_arr=q_arr, d_sc=d_sc, sc=sc,",
        indent + "    p1_arr=p1_arr, is_p4=is_p4)",
        indent + ARM_C_END,
        indent + "p_nosig = 1.0 - p_recv",
    ]
    new_lines = lines[:s] + repl + lines[e + 1:]
    raw = "\n".join(new_lines)
    raw = raw.replace("def decide_action(", "def _decide_with_model(", 1)
    # 供机检复核的是**带缩进的原样文本**（与冻结源码逐行可比）；
    # 实际 exec 用 dedent 后的版本（独立函数定义不能带类体缩进）。
    code = textwrap.dedent(raw)
    ns = {"np": np, "math": math, "ConservativeGrid": ConservativeGrid}
    exec(compile(code, "<frozen-decide-action-with-arm-c-substitution>", "exec"), ns)
    return ns["_decide_with_model"], raw

# 标记：臂 C 唯一改动的边界（check_mechanism.py 依赖这两个字符串）
ARM_C_BEGIN = "# ===== ARM C 唯一改动（开始）====="
ARM_C_END = "# ===== ARM C 唯一改动（结束）====="


def frozen_recv_prob(d_sc, sc, q_arr, p1_arr, is_p4):
    """
    冻结版接收概率公式的**逐字复刻**，仅在臂 C 回退时使用，
    保证"回退 == 基线行为"。
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


# ============================================================================
# 臂 B：k=1 简单止损（基类与基线完全一致）
# ============================================================================
class K1StopFrozenDecision(FrozenDecisionMaker):
    """已有 k=1 规则：连续 1 次补测未使存活集收缩 => 强制转入清除"""

    def __init__(self, k: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.k = int(k)
        self._blind = {}
        self._last_count = {}
        self._last_action = {}
        self.forced_clear_count = 0
        self.action_changed_count = 0
        self.position_changed_count = 0
        self.decision_records = []

    def decide_action(self, cur_p, channel, grid, followup_count, followup_time_s,
                      force_clear, anchor_a=None, measured_positions=None,
                      cur_channel=None, is_p4=False, p1=None):
        cur_count = int(grid.count())
        prev = self._last_count.get(channel)
        if self._last_action.get(channel) == "measure" and prev is not None:
            self._blind[channel] = (self._blind.get(channel, 0) + 1
                                    if cur_count >= prev else 0)

        triggered = False
        if not force_clear and self._blind.get(channel, 0) >= self.k:
            force_clear = True
            triggered = True
            self.forced_clear_count += 1

        res = super().decide_action(
            cur_p=cur_p, channel=channel, grid=grid,
            followup_count=followup_count, followup_time_s=followup_time_s,
            force_clear=force_clear, anchor_a=anchor_a,
            measured_positions=measured_positions, cur_channel=cur_channel,
            is_p4=is_p4, p1=p1)

        if triggered:
            res["reason"] = f"k1_forced_clear (blind={self._blind.get(channel, 0)})"
            res["k_rule_triggered"] = True
            # 在同一状态上算一次"若没有 k 规则，冻结基线会怎么做"，用于精确统计动作变化
            snap = (self.empty_prediction_count, self.unrepresentable_prediction_count,
                    getattr(self, "plan_uncovered_count", 0))
            base = FrozenDecisionMaker.decide_action(
                self, cur_p=cur_p, channel=channel, grid=grid,
                followup_count=followup_count, followup_time_s=followup_time_s,
                force_clear=False, anchor_a=anchor_a,
                measured_positions=measured_positions, cur_channel=cur_channel,
                is_p4=is_p4, p1=p1)
            (self.empty_prediction_count, self.unrepresentable_prediction_count) = snap[:2]
            if hasattr(self, "plan_uncovered_count"):
                self.plan_uncovered_count = snap[2]
            same_action = (base["action_type"] == res["action_type"])
            same_pos = (tuple(np.round(np.asarray(base["position"], dtype=float), 2))
                        == tuple(np.round(np.asarray(res["position"], dtype=float), 2)))
            if not same_action:
                self.action_changed_count += 1
            elif not same_pos:
                self.position_changed_count += 1
            self.decision_records.append({
                "channel": int(channel), "grid_count": cur_count,
                "base_action": base["action_type"],
                "base_pos": [round(float(x), 2) for x in np.asarray(base["position"], dtype=float)],
                "base_j0": base.get("j0"), "base_jq": base.get("best_jq"),
                "b_action": res["action_type"],
                "b_pos": [round(float(x), 2) for x in np.asarray(res["position"], dtype=float)],
                "action_changed": (not same_action),
            })

        self._last_count[channel] = cur_count
        self._last_action[channel] = res["action_type"]
        return res

    def audit(self) -> dict:
        return {
            "forced_clear_count": self.forced_clear_count,
            "action_changed_count": self.action_changed_count,
            "position_changed_count": self.position_changed_count,
            "decision_records": self.decision_records,
        }


# ============================================================================
# 臂 C：历史观测条件下的接收预测（不叠加 k 规则）
# ============================================================================
class CHypothesisDecision(FrozenDecisionMaker):
    def __init__(self, observer=None, n_hyp: int = 512, seed: int = 20260912,
                 eps_deg: float | None = None, p_dir: float = 0.5,
                 r_lo: float = 1000.0, r_hi: float = 1500.0, **kwargs):
        super().__init__(**kwargs)
        self.observer = observer
        self.n_hyp = int(n_hyp)
        self.model_seed = int(seed)
        self.eps_deg = eps_deg          # None => 继承安全网格自身的容差
        self.p_dir = float(p_dir)
        self.r_lo, self.r_hi = float(r_lo), float(r_hi)

        self.models = {}
        self._active = None            # (model, update_info)

        # 审计计数
        self.call_fallback_count = 0           # 逐次打分调用中的回退
        self.decision_with_model_count = 0     # 整体用上模型的决策数
        self.decision_fallback_count = 0       # 整体回退到基线的决策数
        self.fallback_reason_hist = {}
        self.fallback_reasons = []
        self.model_score_count = 0
        self.action_changed_count = 0
        self.position_changed_count = 0
        self.decision_records = []
        self.model_update_records = []

    # ---------------- 模型准备与回退 ----------------
    def _prepare_model(self, channel, grid):
        obs = self.observer.history(channel) if self.observer is not None else []
        m = self.models.get(channel)
        if m is None:
            # 假设集直接从"先验 ∩ 当时已有的全部观测"中抽样；
            # R 与 u 在此一次性抽定，之后各次观测只做剔除
            m = ReceptionHypothesisModel(
                channel=channel, grid=grid, n_hyp=self.n_hyp,
                seed=self.model_seed + 131 * int(channel),
                eps_deg=self.eps_deg, p_dir=self.p_dir,
                r_lo=self.r_lo, r_hi=self.r_hi, observations=obs)
            self.models[channel] = m
        info = m.update(obs)
        self.model_update_records.append(info)
        self._active = (m, info)
        if m.is_usable():
            self.decision_with_model_count += 1
        else:
            self.decision_fallback_count += 1
        return m

    def _recv_prob_or_fallback(self, channel, q_arr, d_sc, sc, p1_arr, is_p4):
        """臂 C 的唯一改动点：优先用假设模型；不可用时逐字回退冻结公式"""
        m, info = self._active if self._active is not None else (None, {})
        reason = None
        if m is None:
            reason = "model_not_initialized"
        elif not m.is_usable():
            reason = m.exhausted_reason or "no_compatible_hypothesis"
        if reason is None:
            p = m.recv_prob(q_arr)
            if p is None:
                reason = "recv_prob_returned_none"
            else:
                self.model_score_count += 1
                return p
        # 回退：与基线逐字一致
        self.call_fallback_count += 1
        self.fallback_reason_hist[reason] = self.fallback_reason_hist.get(reason, 0) + 1
        if len(self.fallback_reasons) < 50:
            self.fallback_reasons.append({
                "channel": int(channel), "reason": reason,
                "n_alive": (m.n_alive if m is not None else None),
                "n_obs": (info.get("n_obs") if isinstance(info, dict) else None),
            })
        return frozen_recv_prob(d_sc, sc, q_arr, p1_arr, is_p4)

    # ---------------- 与冻结版逐字相同的决策主体（程序化生成） ----------------
    # 手工逐字复制极易漏注释/漏行（实测确实漏了 17 处）。这里改为
    #   「读取冻结版 decide_action 的源码 -> 只替换接收概率那一个切片 -> 生成方法」
    # 由构造保证"除被标记块之外逐字相同"，并留下 _generated_source 供机检复核。
    _decide_with_model, _generated_source = build_decide_with_model()

    # ---------------- 对外入口：同时算出"基线若在此状态会怎么做" ----------------
    def decide_action(self, cur_p, channel, grid, followup_count, followup_time_s,
                      force_clear, anchor_a=None, measured_positions=None,
                      cur_channel=None, is_p4=False, p1=None):
        self._prepare_model(channel, grid)

        # 用冻结基类在**完全相同状态**上算出对照决策（只读，不影响模型）
        snap = (self.empty_prediction_count, self.unrepresentable_prediction_count,
                getattr(self, "plan_uncovered_count", 0))
        base = FrozenDecisionMaker.decide_action(
            self, cur_p=cur_p, channel=channel, grid=grid,
            followup_count=followup_count, followup_time_s=followup_time_s,
            force_clear=force_clear, anchor_a=anchor_a,
            measured_positions=measured_positions, cur_channel=cur_channel,
            is_p4=is_p4, p1=p1)
        (self.empty_prediction_count, self.unrepresentable_prediction_count) = snap[:2]
        if hasattr(self, "plan_uncovered_count"):
            self.plan_uncovered_count = snap[2]

        res = self._decide_with_model(
            cur_p=cur_p, channel=channel, grid=grid,
            followup_count=followup_count, followup_time_s=followup_time_s,
            force_clear=force_clear, anchor_a=anchor_a,
            measured_positions=measured_positions, cur_channel=cur_channel,
            is_p4=is_p4, p1=p1)

        m, info = self._active
        same_action = (base["action_type"] == res["action_type"])
        same_pos = (tuple(np.round(np.asarray(base["position"], dtype=float), 2))
                    == tuple(np.round(np.asarray(res["position"], dtype=float), 2)))
        if not same_action:
            self.action_changed_count += 1
        elif not same_pos:
            self.position_changed_count += 1

        # 记录"最近一次观测更新前后"的接收预测（用于机制验证的完整例子）
        # 口径：**同一个粒子群**上用 obs[:-1] 与 obs 分别过滤，属于纯过滤对比，
        #       不涉及重新抽样，因此差异可完全归因于"新观测"本身。
        probe = {}
        obs_at_decision = self.observer.history(channel) if self.observer is not None else []
        if self.observer is not None and m is not None:
            b_pos = np.asarray(base["position"], dtype=float)
            c_pos = np.asarray(res["position"], dtype=float)
            prior_obs = obs_at_decision[:-1] if obs_at_decision else []
            probe = {
                "n_obs_at_decision": len(obs_at_decision),
                "n_alive_before": m.n_alive_with_history(prior_obs),
                "n_alive_after": m.n_alive,
                "p_recv_before_at_base_pos": m.recv_prob_with_history(b_pos, prior_obs),
                "p_recv_after_at_base_pos": m.recv_prob(b_pos),
                "p_recv_before_at_c_pos": m.recv_prob_with_history(c_pos, prior_obs),
                "p_recv_after_at_c_pos": m.recv_prob(c_pos),
            }

        self.decision_records.append({
            "channel": int(channel),
            "grid_count": int(grid.count()),
            "n_obs_at_decision": len(obs_at_decision),
            "obs_at_decision": [
                {"kind": h["kind"], "p": [round(h["p"][0], 2), round(h["p"][1], 2)],
                 "svd": h["svd"]} for h in obs_at_decision[-10:]],
            "n_alive": m.n_alive if m is not None else None,
            "base_action": base["action_type"],
            "base_pos": [round(float(x), 2) for x in np.asarray(base["position"], dtype=float)],
            "base_j0": base.get("j0"), "base_jq": base.get("best_jq"),
            "base_reason": base.get("reason"),
            "c_action": res["action_type"],
            "c_pos": [round(float(x), 2) for x in np.asarray(res["position"], dtype=float)],
            "c_j0": res.get("j0"), "c_jq": res.get("best_jq"),
            "action_changed": (not same_action),
            "position_changed": (same_action and not same_pos),
            "c_reason": res.get("reason"),
            "recv_probe": probe,
        })
        return res

    # ---------------- 审计汇总 ----------------
    def audit(self) -> dict:
        return {
            "decision_with_model_count": self.decision_with_model_count,
            "decision_fallback_count": self.decision_fallback_count,
            "call_fallback_count": self.call_fallback_count,
            "model_score_count": self.model_score_count,
            "fallback_reason_hist": self.fallback_reason_hist,
            "fallback_reasons_sample": self.fallback_reasons[:20],
            "action_changed_count": self.action_changed_count,
            "position_changed_count": self.position_changed_count,
            "n_models": len(self.models),
            "models": [m.snapshot() for m in self.models.values()],
            "model_updates": self.model_update_records,
            "decision_records": self.decision_records,
        }
