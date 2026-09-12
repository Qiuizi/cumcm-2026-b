"""
reception_model.py —— 阶段2 唯一新机制：历史观测条件下的接收预测

设计契约（与任务说明书一一对应）
============================================================
维护对象：**已发现目标**（每个频道一个模型），假设集
    H = { h_i = (x_i, tau_i, R_i, u_i) },  i = 1..M
      x_i  候选真位置（从**当前安全网格的存活单元**中抽样，不含任何真值）
      tau_i ∈ {omni, dir}        源类型
      R_i ∈ [1000, 1500]         接收半径（**同一目标各次观测之间固定**）
      u_i ∈ [0, 2π)              定向源朝向（**同一目标各次观测之间固定**）

容差判据（阳性与阴性**联合**解释）
--------------------------------------------------
记 p 为观测点、x 为候选真位置：
  is_recv(p; h) = ( ||p - x|| <= R )  AND  ( tau = omni  OR  (p - x)·u >= 0 )
  - 观测 "direction" @ p, 示向度 θ：要求 is_recv(p;h)=True，
    且 |angle(x - p) - θ| <= eps（测向误差界）。
  - 观测 "no_signal" @ p          ：要求 is_recv(p;h)=False 。
  - 观测 "near" @ p               ：要求 ||p - x|| <= 5 。
不相容的假设被剔除；每次更新都用**全部历史观测**重新过滤，而不是只参考首次阳性点。

预测
--------------------------------------------------
  P_recv(q) = #{h 相容 : is_recv(q;h)} / #{h 相容}
  P_near(q) = #{h 相容 : ||q - x|| <= 5} / #{h 相容}
全部假设不相容时返回 None，由调用方回退到原有安全流程。

建模假设声明（**不是题面事实**）
--------------------------------------------------
  p_dir = 0.5         源为定向源的比例（本地参考环境默认 dir_ratio=0.5）
  R ~ U[1000,1500]    接收半径分布
  u ~ U[0,2π)         定向源朝向分布
  以上均为**建模假设**，用于构造先验假设集；报告中不得写成赛题事实。

绝对红线（本模块保证）
--------------------------------------------------
  1. 本模块**不持有、不读取、不使用**真值；位置只来自 safety grid。
  2. 本模块**不修改** safety grid（不调用任何 prune/裁剪），
     因此不可能删除真实可能位置。
  3. 本模块**不参与**判空、结束判据、清除计划生成；只输出一个概率给补测评分。
"""

from __future__ import annotations

import math

import numpy as np

EPS_DEG_DEFAULT = 1.005
P_DIR_DEFAULT = 0.5
R_LO_DEFAULT = 1000.0
R_HI_DEFAULT = 1500.0
N_HYP_DEFAULT = 512
POOL_FACTOR_DEFAULT = 40
NEAR_RADIUS_M = 5.0


def angle_diff_deg(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def consistent_mask(x, tau_dir, R, u, observations, eps_deg):
    """
    h=(x,tau,R,u) 是否与全部观测相容（阳性与阴性**联合**解释）。
    向量化；x 为 (M,2)，其余为 (M,)。
    """
    alive = np.ones(len(x), dtype=bool)
    for obs in observations:
        kind = obs["kind"]
        px, py = float(obs["p"][0]), float(obs["p"][1])
        dx = x[:, 0] - px
        dy = x[:, 1] - py
        dist = np.hypot(dx, dy)
        inside = dist <= R
        ux = np.cos(u)
        uy = np.sin(u)
        beam_ok = (-dx) * ux + (-dy) * uy >= 0.0
        recv = inside & ((~tau_dir) | beam_ok)
        if kind == "direction":
            ang = np.degrees(np.arctan2(dy, dx)) % 360.0
            svd = float(obs["svd"])
            adiff = np.abs((ang - svd + 180.0) % 360.0 - 180.0)
            alive &= recv & (adiff <= eps_deg + 1e-9)
        elif kind == "no_signal":
            alive &= ~recv
        elif kind == "near":
            alive &= dist <= NEAR_RADIUS_M
    return alive


class ReceptionHypothesisModel:
    """单个已发现目标的相容假设集与接收预测"""

    def __init__(
        self,
        channel: int,
        grid,
        n_hyp: int = N_HYP_DEFAULT,
        seed: int = 0,
        eps_deg: float | None = None,
        p_dir: float = P_DIR_DEFAULT,
        r_lo: float = R_LO_DEFAULT,
        r_hi: float = R_HI_DEFAULT,
        observations=None,
        pool_factor: int = POOL_FACTOR_DEFAULT,
        max_rounds: int = 6,
    ):
        """
        observations: 建模时刻**已经发生**的历史观测。假设集直接从
                      "先验 ∩ 这些观测" 中抽样（R、u 在此一次性抽定，之后只做剔除）。
        """
        self.channel = int(channel)
        # 测向容差默认**继承生成安全网格的那个容差**，保证模型与网格自洽
        if eps_deg is None:
            eps_deg = float(getattr(grid, "eps_deg", EPS_DEG_DEFAULT))
        self.eps_deg = float(eps_deg)
        self.p_dir = float(p_dir)
        self.r_lo, self.r_hi = float(r_lo), float(r_hi)

        observations = list(observations or [])
        cells = np.asarray(grid.get_surviving_cells(), dtype=float)
        rng = np.random.default_rng(seed)

        acc_x, acc_tau, acc_R, acc_u = [], [], [], []
        have = 0
        if len(cells) > 0:
            for _ in range(max_rounds):
                pool_n = max(int(n_hyp) * int(pool_factor), 2048)
                idx = rng.integers(0, len(cells), size=pool_n)
                Xp = cells[idx]
                tau_p = rng.random(pool_n) < self.p_dir
                Rp = rng.uniform(self.r_lo, self.r_hi, pool_n)
                up = rng.uniform(0.0, 2.0 * math.pi, pool_n)
                keep = consistent_mask(Xp, tau_p, Rp, up, observations, self.eps_deg)
                if keep.any():
                    acc_x.append(Xp[keep])
                    acc_tau.append(tau_p[keep])
                    acc_R.append(Rp[keep])
                    acc_u.append(up[keep])
                    have += int(keep.sum())
                if have >= int(n_hyp):
                    break

        if have == 0:
            self.x = np.zeros((0, 2))
            self.R = np.zeros(0)
            self.u = np.zeros(0)
            self.tau_dir = np.zeros(0, dtype=bool)
        else:
            X = np.concatenate(acc_x)
            T = np.concatenate(acc_tau)
            RR = np.concatenate(acc_R)
            UU = np.concatenate(acc_u)
            if len(X) > int(n_hyp):
                # 等间隔取子样，保持空间分散（确定性）
                sel = np.linspace(0, len(X) - 1, int(n_hyp), dtype=int)
                X, T, RR, UU = X[sel], T[sel], RR[sel], UU[sel]
            self.x, self.tau_dir, self.R, self.u = X, T, RR, UU

        m = len(self.x)
        self.alive = np.ones(m, dtype=bool)
        self.n_hyp_total = m
        self.n_obs_applied = 0
        self.last_eliminated = 0
        self.exhausted_reason: str | None = None
        if m == 0:
            self.exhausted_reason = (
                f"prior_conditioned_on_{len(observations)}_observations_has_no_sample"
            )
        self.grid_count_at_init = int(grid.count())

    # ------------------------------------------------------------------
    @property
    def n_alive(self) -> int:
        return int(self.alive.sum())

    def is_usable(self) -> bool:
        return self.n_alive > 0

    # ------------------------------------------------------------------
    def _receives(self, px: float, py: float, alive_mask=None):
        """
        向量化：对每个**存活**假设判断"若源在 x_i，则位于 (px,py) 的测站能否收到"
        返回 (recv_bool_alive, dist_alive, inside_recv_alive)
        """
        base = self.alive if alive_mask is None else alive_mask
        idx = np.nonzero(base)[0]
        if len(idx) == 0:
            return None, None, None
        dx = self.x[idx, 0] - px
        dy = self.x[idx, 1] - py
        dist = np.hypot(dx, dy)
        inside = dist <= self.R[idx]
        # 源 -> 测站 的向量为 (-dx, -dy)
        ux = np.cos(self.u[idx])
        uy = np.sin(self.u[idx])
        beam_ok = (-dx) * ux + (-dy) * uy >= 0.0
        recv = inside & ((~self.tau_dir[idx]) | beam_ok)
        return recv, dist, inside

    def recv_prob(self, q) -> float | None:
        """P_recv(q)；全部假设不相容时返回 None（调用方回退）"""
        recv, _, _ = self._receives(float(q[0]), float(q[1]))
        if recv is None or len(recv) == 0:
            return None
        return float(np.mean(recv))

    # ---- 同一粒子群上的"纯过滤"对比工具（供机制验证使用）----
    def alive_mask_with_history(self, observations):
        if self.n_hyp_total == 0:
            return np.zeros(0, dtype=bool)
        return consistent_mask(self.x, self.tau_dir, self.R, self.u,
                               list(observations), self.eps_deg)

    def n_alive_with_history(self, observations) -> int:
        return int(self.alive_mask_with_history(observations).sum())

    def recv_prob_with_history(self, q, observations) -> float | None:
        """在同一粒子群上，用给定观测集重新过滤后的 P_recv"""
        mask = self.alive_mask_with_history(observations)
        recv, _, _ = self._receives(float(q[0]), float(q[1]), alive_mask=mask)
        if recv is None or len(recv) == 0:
            return None
        return float(np.mean(recv))

    def near_prob(self, q) -> float | None:
        idx = np.nonzero(self.alive)[0]
        if len(idx) == 0:
            return None
        d = np.hypot(self.x[idx, 0] - float(q[0]), self.x[idx, 1] - float(q[1]))
        return float(np.mean(d <= NEAR_RADIUS_M))

    # ------------------------------------------------------------------
    def update(self, observations) -> dict:
        """
        用**全部**历史观测重新过滤假设集（阳性与阴性联合解释）。
        observations: [{"kind": "direction"|"no_signal"|"near", "p": (x,y), "svd": deg}, ...]
        返回诊断字典。注意：这里只做剔除，R 与 u 不重新随机。
        """
        self.n_obs_applied = len(observations)
        before = self.n_alive
        alive = np.ones(self.n_hyp_total, dtype=bool)
        if self.n_hyp_total:
            alive = consistent_mask(self.x, self.tau_dir, self.R, self.u,
                                    list(observations), self.eps_deg)

        self.alive = alive
        self.last_eliminated = before - self.n_alive
        if self.n_alive == 0 and self.exhausted_reason is None:
            self.exhausted_reason = (
                f"all_hypotheses_incompatible_after_{len(observations)}_observations"
            )
        return {
            "channel": self.channel,
            "n_obs": len(observations),
            "n_alive_before": before,
            "n_alive_after": self.n_alive,
            "eliminated": self.last_eliminated,
            "exhausted": not self.is_usable(),
            "exhausted_reason": self.exhausted_reason,
        }

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "channel": self.channel,
            "n_hyp_total": self.n_hyp_total,
            "n_alive": self.n_alive,
            "n_obs_applied": self.n_obs_applied,
            "grid_count_at_init": self.grid_count_at_init,
            "R_range": [round(float(self.R.min()), 2), round(float(self.R.max()), 2)]
            if self.n_hyp_total else None,
            "dir_fraction": round(float(self.tau_dir.mean()), 4) if self.n_hyp_total else None,
        }
