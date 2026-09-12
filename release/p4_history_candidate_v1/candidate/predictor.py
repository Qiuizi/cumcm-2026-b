"""
predictor.py —— 候选版的接收预测接口与冻结实现

接口（ReceptionPredictor 协议）
--------------------------------------------------
    prepare_for_decision(channel, grid) -> dict     # 建立/增量更新该目标的假设集
    reception_probability(q) -> float | None        # P_recv(q)；None = 不可用，需回退

冻结声明（本文件内所有常量即是"冻结的当前历史模型"，本轮不得再调）
--------------------------------------------------
    N_HYP        = 512      假设（粒子）数量
    P_DIR        = 0.5      源为定向源的比例        ← 建模假设，非题面事实
    R_LO/R_HI    = 1000/1500 接收半径先验区间        ← 建模假设
    U_PRIOR      = 均匀      朝向先验                ← 建模假设
    EPS          = None      测向容差继承安全网格自身的 eps_deg（保持与网格自洽）
    POOL_FACTOR  = 40        条件化抽样池倍数
    MAX_ROUNDS   = 6         条件化抽样轮数上限
    SEED_BASE    = 20260912  先验抽样基准种子
    SEED_STRIDE  = 131       每频道的种子步长（保证同一目标 R/u 固定且可复现）
    更新规则     = 用**全部历史观测**重新过滤相容假设（阳性+阴性联合解释），只做剔除，
                   绝不重新抽取 R/u
    回退规则     = 假设集为空 ⇒ reception_probability 返回 None ⇒ 决策器逐字回退冻结公式，
                   记录原因与次数；不删除安全网格、不丢源、不改结束判据
"""

from __future__ import annotations

import os
import sys
from typing import Protocol, runtime_checkable

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from model import ReceptionHypothesisModel  # noqa: E402  （冻结的模型实现）


@runtime_checkable
class ReceptionPredictor(Protocol):
    def prepare_for_decision(self, channel: int, grid) -> dict: ...
    def reception_probability(self, q) -> float | None: ...


class HistoryReceptionPredictor:
    """冻结先验的历史接收模型预测器（每个频道一个假设集）"""

    # ---- 冻结常量（本轮不得调参）----
    N_HYP = 512
    P_DIR = 0.5
    R_LO = 1000.0
    R_HI = 1500.0
    POOL_FACTOR = 40
    MAX_ROUNDS = 6
    SEED_BASE = 20260912
    SEED_STRIDE = 131

    def __init__(self, observer, record_updates: bool = True):
        self.observer = observer
        self.record_updates = bool(record_updates)
        self.models = {}
        self._last_obs_len = {}
        self._active_channel = None
        self.last_unavailable_reason = None

        # 最近一次 prepare_for_decision 的状态（供决策记录留痕）
        self.last_n_alive = None
        self.last_n_obs = None
        self.last_usable = None

        self.update_records = []
        self.created_channels = []

    # ------------------------------------------------------------------
    def _observations(self, channel: int):
        if self.observer is None:
            return []
        return self.observer.history(channel)

    def prepare_for_decision(self, channel: int, grid) -> dict:
        """
        建立或增量更新 channel 的假设集；返回本次决策的诊断。
        decision_counted 表示"本次决策确实进入了模型评分阶段"。
        """
        channel = int(channel)
        obs = self._observations(channel)

        m = self.models.get(channel)
        created = False
        if m is None:
            m = ReceptionHypothesisModel(
                channel=channel, grid=grid, n_hyp=self.N_HYP,
                seed=self.SEED_BASE + self.SEED_STRIDE * channel,
                eps_deg=None,                      # 继承安全网格的 eps_deg
                p_dir=self.P_DIR, r_lo=self.R_LO, r_hi=self.R_HI,
                observations=obs,                  # 先验 ∩ 当时已有观测
                pool_factor=self.POOL_FACTOR, max_rounds=self.MAX_ROUNDS)
            self.models[channel] = m
            self.created_channels.append(channel)
            created = True

        # 更新规则：观测条数变化即重放全部历史观测做剔除
        info = None
        if created or self._last_obs_len.get(channel) != len(obs):
            info = m.update(obs)
            self._last_obs_len[channel] = len(obs)
            if self.record_updates:
                self.update_records.append(info)

        self._active_channel = channel
        usable = m.is_usable()
        self.last_unavailable_reason = (None if usable
                                        else (m.exhausted_reason
                                              or "no_compatible_hypothesis"))
        self.last_n_alive = m.n_alive
        self.last_n_obs = len(obs)
        self.last_usable = usable
        return {
            "channel": channel,
            "usable": usable,
            "n_alive": m.n_alive,
            "n_obs": len(obs),
            "created": created,
            "updated": info is not None,
            "decision_counted": True,
        }

    # ------------------------------------------------------------------
    def reception_probability(self, q) -> float | None:
        m = self.models.get(self._active_channel)
        if m is None or not m.is_usable():
            return None
        return m.recv_prob(q)

    def recv_prob_with_history(self, q, observations):
        """仅用于事后分析：同一粒子群上的纯过滤对比"""
        m = self.models.get(self._active_channel)
        if m is None:
            return None
        return m.recv_prob_with_history(q, observations)

    # ------------------------------------------------------------------
    def describe(self) -> dict:
        """候选版配置与冻结标识（供启动入口打印）"""
        return {
            "predictor_class": f"{self.__class__.__name__}",
            "predictor_module": os.path.join(HERE, "predictor.py"),
            "model_module": os.path.join(HERE, "model.py"),
            "frozen_prior": {
                "n_hyp": self.N_HYP,
                "p_dir": self.P_DIR,
                "r_range": [self.R_LO, self.R_HI],
                "u_prior": "uniform[0,2pi)",
                "eps_deg": "inherit_from_grid",
                "pool_factor": self.POOL_FACTOR,
                "max_rounds": self.MAX_ROUNDS,
                "seed_base": self.SEED_BASE,
                "seed_stride": self.SEED_STRIDE,
            },
            "update_rule": "refilter_all_compatible_hypotheses_with_full_history",
            "fallback_rule": "empty_hypothesis_set -> return None -> frozen_recv_prob",
            "n_models_created": len(self.models),
        }
