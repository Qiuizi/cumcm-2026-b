"""
wiring.py —— 发布包接线助手（路径为包内相对；逻辑与验收版一致）

职责（本文件不实现任何决策逻辑，只做接线、核对与取证）
--------------------------------------------------
1. `verify_provenance()`     核对"候选构建所用冻结源码指纹"与"实际加载的模块"是否一致
2. `check_truth_isolation()` 对候选模块做 AST 静态检查，确认不访问真值/环境内部字段
3. `build_candidate()`       **直接复用**本轮验证的候选模块（不另写一份决策实现）
4. `observation_is_interface_only()` 观测字典只允许接口字段

红线
--------------------------------------------------
* 不修改候选模块；不改动 P3、P4 覆盖布局、扫描规则、全局调度与结束判据
* 不读取 case / env.sources / 本地模拟器特有字段
* 历史模型只消费 HTTP 接口返回的 measure_result / svd_deg
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys

CANDIDATE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(CANDIDATE_DIR)          # 发布包根
FREEZE_PATH = os.path.join(REPO_ROOT, "FREEZE.json")

if CANDIDATE_DIR not in sys.path:
    sys.path.insert(0, CANDIDATE_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# 候选实现（本轮验证过的同一批文件，不得另写副本）
CANDIDATE_MODULE_FILES = [
    "candidate/model.py",
    "candidate/predictor.py",
    "candidate/candidate_decision.py",
    "candidate/observer.py",
    "candidate/wiring.py",
]

# 真值隔离静态检查的黑名单
FORBIDDEN_ATTRS = {"sources", "is_directional", "orientation_deg"}
FORBIDDEN_NAMES = {"SimEnvironment", "RadioSource"}

# 观测字典允许出现的字段（只来自 HTTP 接口响应）
ALLOWED_OBS_KEYS = {"kind", "p", "svd"}


def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_freeze(path: str = FREEZE_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verify_provenance(freeze_path: str = FREEZE_PATH) -> dict:
    """
    核对：
      (a) 候选文件的实际 sha256 == FREEZE.json 记录值
      (b) **实际加载的** local_decision_frozen 模块 sha256 == FREEZE.json 记录的冻结基线值
          （候选决策主体由该冻结源码生成，基类一旦变化，逐字继承的前提就不成立）
      (c) 模型先验常量与 FREEZE.json 的冻结规格一致
    """
    fr = load_freeze(freeze_path)
    checks = {"candidate_files": {}, "frozen_baseline": {}, "all_match": True}

    for rel, rec in fr["candidate_files"].items():
        p = os.path.join(REPO_ROOT, rel)
        actual = sha256_file(p) if os.path.exists(p) else "MISSING"
        ok = (actual == rec["sha256"])
        checks["candidate_files"][rel] = {"expected": rec["sha256"], "actual": actual,
                                          "match": ok}
        checks["all_match"] &= ok

    import local_decision_frozen
    import conservative_grid_frozen
    loaded = {
        "local_decision_frozen.py": local_decision_frozen.__file__,
        "conservative_grid_frozen.py": conservative_grid_frozen.__file__,
    }
    for rel, rec in fr["frozen_baseline_components"].items():
        if rel in loaded:
            actual = sha256_file(loaded[rel])
            ok = (actual == rec["sha256"])
            checks["frozen_baseline"][rel] = {
                "expected": rec["sha256"], "actual": actual, "match": ok,
                "loaded_from": loaded[rel], "role": "候选决策主体的生成来源 / 基类"}
            checks["all_match"] &= ok

    # (c) 模型先验常量
    from predictor import HistoryReceptionPredictor as P
    spec = fr["frozen_model_spec"]
    prior_actual = {
        "n_hyp": P.N_HYP, "p_dir": P.P_DIR, "r_prior": [P.R_LO, P.R_HI],
        "u_prior": "uniform[0,2pi)", "eps_deg": "inherit_from_safety_grid",
        "pool_factor": P.POOL_FACTOR, "max_rounds": P.MAX_ROUNDS,
        "seed_base": P.SEED_BASE, "seed_stride": P.SEED_STRIDE,
        "update_rule": "refilter_all_compatible_hypotheses_with_full_history",
        "fallback_rule": "empty_hypothesis_set -> reception_probability returns None "
                         "-> decision maker falls back to frozen_recv_prob verbatim",
    }
    prior_ok = all(spec.get(k) == v for k, v in prior_actual.items())
    checks["frozen_model_spec"] = {"expected": spec, "actual": prior_actual,
                                   "match": prior_ok}
    checks["all_match"] &= prior_ok
    return checks


def check_truth_isolation(module_files=None) -> dict:
    """AST 静态检查：候选模块不得出现真值/环境内部字段的访问"""
    files = module_files or CANDIDATE_MODULE_FILES
    violations = []
    scanned = []
    for rel in files:
        p = os.path.join(REPO_ROOT, rel)
        if not os.path.exists(p):
            violations.append({"file": rel, "issue": "missing"})
            continue
        scanned.append(rel)
        tree = ast.parse(open(p, encoding="utf-8").read(), filename=p)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
                violations.append({"file": rel, "line": node.lineno,
                                   "issue": f"attribute .{node.attr}"})
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                violations.append({"file": rel, "line": node.lineno,
                                   "issue": f"name {node.id}"})
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                if "sim_env" in (mod or "") or any("sim_env" in n for n in names):
                    violations.append({"file": rel, "line": node.lineno,
                                       "issue": "imports sim_env"})
    return {
        "scanned_files": scanned,
        "forbidden_attrs": sorted(FORBIDDEN_ATTRS),
        "forbidden_names": sorted(FORBIDDEN_NAMES),
        "violations": violations,
        "clean": len(violations) == 0,
    }


def observation_is_interface_only(obs: dict) -> bool:
    return set(obs.keys()) <= ALLOWED_OBS_KEYS


def build_candidate(inner_driver):
    """
    直接复用本轮验证的候选模块构造 (observer, predictor, decision)。
    不复制、不重写任何决策或模型逻辑。
    """
    from observer import RecordingObserverDriver
    from predictor import HistoryReceptionPredictor
    from candidate_decision import HistoryCandidateDecision

    observer = RecordingObserverDriver(inner_driver)
    predictor = HistoryReceptionPredictor(observer=observer, record_updates=True)
    decision = HistoryCandidateDecision(
        predictor=predictor, max_followups=12, max_followup_time_s=600.0, margin_s=5.0)
    return observer, predictor, decision


def describe_candidate(observer, predictor, decision) -> dict:
    """启动时打印/落盘用的候选说明"""
    from candidate_decision import HistoryCandidateDecision  # noqa: F401
    return {
        "decision_class": f"{type(decision).__module__}.{type(decision).__name__}",
        "decision_module_file": sys.modules[type(decision).__module__].__file__,
        "predictor_class": f"{type(predictor).__module__}.{type(predictor).__name__}",
        "predictor_module_file": sys.modules[type(predictor).__module__].__file__,
        "observer_class": f"{type(observer).__module__}.{type(observer).__name__}",
        "observer_module_file": sys.modules[type(observer).__module__].__file__,
        "predictor_frozen_prior": predictor.describe()["frozen_prior"],
        "update_rule": predictor.describe()["update_rule"],
        "fallback_rule": predictor.describe()["fallback_rule"],
        "observation_keys_allowed": sorted(ALLOWED_OBS_KEYS),
        "decision_limits": {
            "max_followups": decision.max_followups,
            "max_followup_time_s": decision.max_followup_time_s,
            "margin_s": decision.margin_s,
        },
    }
