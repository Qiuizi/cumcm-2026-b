"""
build_candidate_method.py —— 候选版决策方法的**构建期**生成器（一次性工具，非运行期依赖）

为什么要有这一步
--------------------------------------------------
候选版与冻结基线的唯一差异必须只有"接收概率"那一处。手工誊写实测会漏注释与空行
（第二阶段曾漏 17 处）；而在**运行期**读取冻结源码再 exec 又不适合作为正式候选实现。
折中做法：在**构建期**从冻结源码生成普通 Python 源码并落盘为 `candidate_decision.py`，
运行期只 import 这个普通模块 —— 既不 exec 外部源码，也保证逐行同源。

生成规则
--------------------------------------------------
读取 `local_decision_frozen.LocalDecisionMaker.decide_action` 的源码，
把"接收概率"切片（从 `# 判定是否能收到有效测向信号` 到 `p_nosig = 1.0 - p_recv`）
替换为对显式接口 `self._reception_probability(...)` 的调用，其余逐字保留（含注释与空行），
并把方法名保持为 `decide_action`（就是覆盖基类的方法）。

用法
--------------------------------------------------
    python experiments/stage3_candidate/tools/build_candidate_method.py
"""

from __future__ import annotations

import inspect
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(PKG, "..", ".."))
sys.path.insert(0, ROOT)

from local_decision_frozen import LocalDecisionMaker as FrozenDecisionMaker  # noqa: E402

OUT_PATH = os.path.join(PKG, "candidate_decision.py")

HEADER = '''"""
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

'''

FOOTER = '''
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
'''

# 候选版唯一的替换块（保持与冻结版同一缩进层级）
# 注：生成时直接写入注释文本（而非标识符），使候选源码自解释、便于人工审阅。
REPLACEMENT_LINES = [
    "# ===== HISTORY-CANDIDATE 唯一改动（开始）=====",
    "p_recv = self._reception_probability(",
    "    channel=channel, grid=grid, q_arr=q_arr, d_sc=d_sc, sc=sc,",
    "    p1_arr=p1_arr, is_p4=is_p4)",
    "# ===== HISTORY-CANDIDATE 唯一改动（结束）=====",
    "p_nosig = 1.0 - p_recv",
]


def build() -> str:
    lines = inspect.getsource(FrozenDecisionMaker.decide_action).splitlines()
    s = next(i for i, ln in enumerate(lines) if "判定是否能收到有效测向信号" in ln)
    e = next(i for i, ln in enumerate(lines[s:], start=s)
             if "p_nosig = 1.0 - p_recv" in ln)
    indent = lines[s][:len(lines[s]) - len(lines[s].lstrip())]
    repl = [indent + t for t in REPLACEMENT_LINES]
    body = lines[:s] + repl + lines[e + 1:]
    text = "\n".join(body)
    # 生成的决策主体另起名字，由手写的 decide_action 包装；两者合起来才等价于覆盖基类
    text = text.replace("def decide_action(", "def _decide_with_history(", 1)
    return text


def main():
    method_src = build()
    # inspect.getsource 返回的方法源码**已带类体缩进（4 空格）**，不能再加缩进，
    # 否则 def 会变成嵌套函数、类实际仍继承冻结方法（曾踩过这个坑）。
    first = method_src.splitlines()[0]
    if not first.startswith("    def ") or first.startswith("        "):
        raise SystemExit(f"生成的方法首行缩进异常：{first!r}")
    text = HEADER + "\n" + method_src + "\n" + FOOTER
    with io.open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"已生成 {OUT_PATH}")
    print(f"  生成的方法体行数 = {len(method_src.splitlines())}")
    print(f"  冻结 decide_action 行数 = "
          f"{len(inspect.getsource(FrozenDecisionMaker.decide_action).splitlines())}")

    # ---- 生成后自检：必须在**新进程**里确认生成结果被正确挂到类上 ----
    import subprocess
    check = (
        "import sys, inspect\n"
        f"sys.path.insert(0, {PKG!r})\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "from candidate_decision import HistoryCandidateDecision, CANDIDATE_BEGIN\n"
        "import local_decision_frozen\n"
        "cls = HistoryCandidateDecision\n"
        "assert 'decide_action' in cls.__dict__, 'decide_action 包装未在类体内定义'\n"
        "assert '_decide_with_history' in cls.__dict__, '_decide_with_history 未在类体内定义'\n"
        "src = inspect.getsource(cls._decide_with_history)\n"
        "assert CANDIDATE_BEGIN in src, '_decide_with_history 源码中缺少候选标记'\n"
        "assert src.splitlines()[0].lstrip().startswith('def _decide_with_history')\n"
        "frozen = inspect.getsource(local_decision_frozen.LocalDecisionMaker.decide_action)\n"
        "print('SELFCHECK OK wrapper=%s body=%d frozen=%d' % (\n"
        "    'decide_action' in cls.__dict__, len(src.splitlines()),\n"
        "    len(frozen.splitlines())))\n"
    )
    r = subprocess.run([sys.executable, "-c", check], capture_output=True, text=True,
                       encoding="utf-8")
    print((r.stdout or "").strip())
    if r.returncode != 0:
        raise SystemExit("自检失败：\n" + (r.stderr or ""))


if __name__ == "__main__":
    main()
