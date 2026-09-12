"""
write_freeze.py —— 生成 FREEZE.json（冻结声明 + 源码标识）

冻结内容（本轮起不得再调）：
  1) 稳定基线依赖的冻结组件
  2) 候选版自身：模型先验、假设数量、更新规则、回退规则、生成后的决策模块
同时写入 sha256，供启动入口与验证脚本对照。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(PKG, "..", ".."))

sys.path.insert(0, ROOT)
sys.path.insert(0, PKG)


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


FROZEN_BASELINE = [
    "local_decision_frozen.py",
    "conservative_grid_frozen.py",
    "src/sim_env.py",
    "src/strategy_engine.py",
    "src/evidence_tracker.py",
]

CANDIDATE_FILES = [
    "experiments/stage3_candidate/model.py",
    "experiments/stage3_candidate/predictor.py",
    "experiments/stage3_candidate/candidate_decision.py",
    "experiments/stage3_candidate/observer.py",
    "experiments/stage3_candidate/launch.py",
]


def main():
    from predictor import HistoryReceptionPredictor as P

    out = {
        "stage": "stage3_candidate",
        "frozen_at": "P4 历史接收模型候选版（第三阶段）",
        "frozen_baseline_components": {
            p: {"path": os.path.join(ROOT, p), "sha256": sha(os.path.join(ROOT, p))}
            for p in FROZEN_BASELINE
        },
        "candidate_files": {
            p: {"path": os.path.join(ROOT, p), "sha256": sha(os.path.join(ROOT, p))}
            for p in CANDIDATE_FILES
        },
        "frozen_model_spec": {
            "n_hyp": P.N_HYP,
            "p_dir": P.P_DIR,
            "r_prior": [P.R_LO, P.R_HI],
            "u_prior": "uniform[0,2pi)",
            "eps_deg": "inherit_from_safety_grid",
            "pool_factor": P.POOL_FACTOR,
            "max_rounds": P.MAX_ROUNDS,
            "seed_base": P.SEED_BASE,
            "seed_stride": P.SEED_STRIDE,
            "update_rule": "refilter_all_compatible_hypotheses_with_full_history",
            "fallback_rule": "empty_hypothesis_set -> reception_probability returns None "
                             "-> decision maker falls back to frozen_recv_prob verbatim",
            "note_on_priors": "p_dir / R 区间 / 朝向均匀分布均为建模假设，不是题面事实",
        },
        "identity_checks": {
            "stage2_model_vs_stage3_model": {
                "stage2": sha(os.path.join(ROOT, "experiments/stage2_hypothesis/reception_model.py")),
                "stage3": sha(os.path.join(ROOT, "experiments/stage3_candidate/model.py")),
            },
        },
        "constraints": [
            "不调用官方模拟器；不另建模拟器（只用本地参考环境 src/sim_env.py）",
            "P3、P4 覆盖布局、扫描规则、全局调度、候选补点、清除计划、结束判据均不变",
            "概率模型只影响决策评分；不删除安全网格、不丢源、不参与判空与结束判据",
            "运行期不读取也不 exec 外部源码（candidate_decision.py 为构建期一次性生成）",
        ],
    }
    out["identity_checks"]["stage2_model_vs_stage3_model"]["identical"] = (
        out["identity_checks"]["stage2_model_vs_stage3_model"]["stage2"]
        == out["identity_checks"]["stage2_model_vs_stage3_model"]["stage3"])

    path = os.path.join(PKG, "FREEZE.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已写入 {path}")
    for k, v in out["candidate_files"].items():
        print(f"  {v['sha256'][:16]}  {k}")
    print(f"  冻结模型规格: n_hyp={P.N_HYP}, p_dir={P.P_DIR}, "
          f"R=[{P.R_LO},{P.R_HI}], seed_base={P.SEED_BASE}, stride={P.SEED_STRIDE}")
    print(f"  stage2模型 与 stage3模型 逐字节一致 = "
          f"{out['identity_checks']['stage2_model_vs_stage3_model']['identical']}")


if __name__ == "__main__":
    main()
