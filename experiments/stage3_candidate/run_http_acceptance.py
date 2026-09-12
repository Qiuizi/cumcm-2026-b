"""
run_http_acceptance.py —— 有限交付验收：把已验证的 P4 history_candidate 通过 HTTP 入口跑一遍并核对

只用**已有本地替代 HTTP 服务**（src/mock_server.py，由 run_port_test.py 自动拉起），
不调用官方模拟器、不另建模拟器。

三局（同一既有合法场景：P4 / 10 源 / mock seed 9501）
  R1  --prob p4 --profile stable            (端口 14026)
  R2  --prob p4 --profile history_candidate (端口 14027)
  R3  --prob p3 --profile stable            (端口 14028, 用于核对 P3 既有入口配置不变)

核对项
  A. 实际调用的决策器、模型参数与模块指纹
  B. 候选已脱离本地真值访问（静态 AST + 观测字段白名单 + 接口层无真值字段）
  C. 完整清除、逐频道结束证据成立、计费闭合
  D. 接线前后在相同输入观测下决策一致（HTTP 候选 vs 本地环境候选，同场景同种子）
  E. P3 的既有入口配置保持不变
"""

from __future__ import annotations

import ast
import csv
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import wiring  # noqa: E402

OUT_DIR = os.path.join(ROOT, "results", "delivery")
SESSION_DIR = os.path.join(OUT_DIR, "http_sessions")
PATCH_SCRIPT = os.path.join(ROOT, "scratch", "apply_port_wiring.py")

SCENARIO = {"prob": "p4", "sources": 10, "mock_seed": 9501}
RUNS = [
    {"tag": "R1", "profile": "stable", "port": 14026, "prob": "p4"},
    {"tag": "R2", "profile": "history_candidate", "port": 14027, "prob": "p4"},
    {"tag": "R3", "profile": "stable", "port": 14028, "prob": "p3"},
]
P3_REFERENCE = os.path.join(OUT_DIR, "entry_validation_stable.json")
# 同一含义的不同措辞（不影响语义，仅用于规范化比较）
PRIOR_ALIASES = {"inherit_from_grid": "inherit_from_safety_grid"}
CONFIG_KEYS = ["is_p4", "version", "enable_pruning", "scan_at_clearance",
               "enable_2opt_head", "enable_adaptive_radial_coverage",
               "grid_class", "local_decision_class"]


def ensure_wiring():
    """
    幂等确保接线已应用。

    注意：本工作区存在**将已跟踪文件周期性恢复为 HEAD** 的外部行为
    （实测两次：一次打断 history_candidate 运行，一次打断本验收的第三局）。
    因此这里在**每一局运行前**都重新确认并（必要时）重放接线补丁，
    并把源码差异单独导出为 patch 文件作为交付物 —— 不依赖工作区文件长期保持修改态。
    """
    with open(os.path.join(ROOT, "scripts", "run_port_test.py"), encoding="utf-8") as f:
        src = f.read()
    ok = ("PROFILE_HISTORY" in src) and ("session_dir" in src) and ("base_driver" in src)
    if ok:
        return {"applied": True, "action": "already-applied"}
    r = subprocess.run([sys.executable, PATCH_SCRIPT], capture_output=True, text=True,
                       encoding="utf-8")
    return {"applied": r.returncode == 0, "action": "re-applied",
            "stdout": r.stdout, "stderr": r.stderr}


def export_wiring_diff():
    """把 run_port_test.py 相对 HEAD 的差异导出为 patch（交付用，不依赖文件保持修改态）"""
    path = os.path.join(OUT_DIR, "run_port_test_wiring.patch")
    with open(path, "w", encoding="utf-8") as f:
        p = subprocess.run(["git", "diff", "--", "scripts/run_port_test.py"],
                           cwd=ROOT, stdout=f, stderr=subprocess.DEVNULL, text=True,
                           encoding="utf-8")
    size = os.path.getsize(path)
    return {"patch_file": path, "bytes": size, "returncode": p.returncode}


def run_entry(tag, profile, port, prob):
    log = os.path.join(OUT_DIR, f"http_acceptance_{tag}_{profile}_{prob}.log")
    cmd = [sys.executable, "scripts/run_port_test.py",
           "--port", str(port), "--prob", prob, "--version", "C",
           "--profile", profile, "--robot_id", "team2026",
           "--sources", str(SCENARIO["sources"]),
           "--mock_seed", str(SCENARIO["mock_seed"]),
           "--session_dir", os.path.relpath(SESSION_DIR, ROOT)]
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                           cwd=ROOT, text=True, encoding="utf-8")
    return {"tag": tag, "profile": profile, "prob": prob, "port": port,
            "cmd": " ".join(cmd), "log": log, "returncode": p.returncode}


def latest_session(profile, prob, not_before):
    """找出该档位最近写入的会话文件（时间戳晚于 not_before）"""
    if not os.path.isdir(SESSION_DIR):
        return None
    cands = [os.path.join(SESSION_DIR, n) for n in os.listdir(SESSION_DIR)
             if n.startswith(f"session_{profile}_{prob}_") and n.endswith(".json")]
    cands = [c for c in cands if os.path.getmtime(c) >= not_before - 1]
    return max(cands, key=os.path.getmtime) if cands else None


def parse_http_trace(jsonl_path):
    """从明文 HTTP 日志解析唯一有效动作序列（按 request_id 去重）"""
    seen = set()
    trace = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            req, resp = e.get("request", {}), e.get("response", {})
            rid = req.get("request_id")
            if rid in seen or not resp.get("accepted"):
                continue
            seen.add(rid)
            path = e.get("path")
            if path == "/measure":
                pos = req.get("position", {})
                trace.append({"kind": "measure",
                              "pos": [float(pos.get("x", 0.0)), float(pos.get("y", 0.0))],
                              "channel": int(req.get("channel", 1)),
                              "result": resp.get("measure_result")})
            elif path == "/clear":
                pos = req.get("position", {})
                trace.append({"kind": "clear",
                              "pos": [float(pos.get("x", 0.0)), float(pos.get("y", 0.0))],
                              "channel": int(req.get("channel", 1)),
                              "result": resp.get("clear_result")})
    return trace, len(seen)


def check_truth_isolation_runtime():
    """接口层是否持有真值字段：AST 扫描 HttpSimDriver"""
    p = os.path.join(ROOT, "src", "client_runner.py")
    tree = ast.parse(open(p, encoding="utf-8").read())
    forbidden = {"sources", "is_directional", "orientation_deg", "env"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            found.append({"line": node.lineno, "attr": node.attr})
    # HttpSimDriver.__init__ 里 self.X = ... 的字段清单
    fields = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "HttpSimDriver":
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and isinstance(sub.targets[0], ast.Attribute)
                        and isinstance(sub.targets[0].value, ast.Name)
                        and sub.targets[0].value.id == "self"):
                    fields.append(sub.targets[0].attr)
    return {"forbidden_attr_hits": found, "clean": len(found) == 0,
            "http_driver_fields": sorted(set(fields))}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(SESSION_DIR, exist_ok=True)
    result = {"scenario": SCENARIO, "runs": [], "checks": {}}

    print("=" * 104)
    print("有限交付验收：P4 history_candidate 接入 HTTP 入口（本地替代 HTTP 服务）")
    print("=" * 104)

    wiring_state = ensure_wiring()
    print(f"\n[接线状态] {wiring_state['action']}  已应用={wiring_state['applied']}")
    result["wiring"] = wiring_state
    if not wiring_state["applied"]:
        print("接线未应用，停止。")
        return
    result["wiring_diff"] = export_wiring_diff()
    print(f"[接线差异] 已导出 patch: {result['wiring_diff']['patch_file']} "
          f"({result['wiring_diff']['bytes']} 字节)")

    import time
    for spec in RUNS:
        # 每局运行前重新确认接线（本工作区存在周期性恢复已跟踪文件的外部行为）
        st = ensure_wiring()
        if not st["applied"]:
            print(f"[{spec['tag']}] 接线无法应用，跳过：{st}")
            result["runs"].append({"tag": spec["tag"], "ok": False,
                                   "error": "wiring_not_applied", "detail": st})
            continue
        t0 = time.time()
        info = run_entry(spec["tag"], spec["profile"], spec["port"], spec["prob"])
        info["started_at"] = t0
        info["wiring_before_run"] = st["action"]
        info["session_file"] = latest_session(spec["profile"], spec["prob"], t0)
        info["ok"] = (info["returncode"] == 0 and info["session_file"] is not None)
        result["runs"].append(info)
        print(f"\n[{info['tag']}] {info['cmd']}")
        print(f"     returncode={info['returncode']}  会话文件={info['session_file']}")
        if not info["ok"]:
            print(f"     ！该局未正常结束，日志见 {info['log']}")

    by_tag = {r["tag"]: r for r in result["runs"]}
    sessions = {}
    for tag, info in by_tag.items():
        if info.get("session_file"):
            with open(info["session_file"], encoding="utf-8") as f:
                sessions[tag] = json.load(f)

    # ---------------- A. 决策器 / 模型参数 / 模块指纹 ----------------
    fr = wiring.load_freeze()
    cfg_stable = sessions.get("R1", {}).get("effective_config", {})
    cfg_hist = sessions.get("R2", {}).get("effective_config", {})
    cand = sessions.get("R2", {}).get("candidate") or {}
    A = {
        "R1_decision_class": cfg_stable.get("local_decision_class"),
        "R1_grid_class": cfg_stable.get("grid_class"),
        "R1_is_frozen_baseline":
            cfg_stable.get("local_decision_class")
            == "local_decision_frozen.LocalDecisionMaker",
        "R2_decision_class": cfg_hist.get("local_decision_class"),
        "R2_decision_module_file": cfg_hist.get("local_decision_module_file"),
        "R2_is_candidate":
            cfg_hist.get("local_decision_class")
            == "candidate_decision.HistoryCandidateDecision",
        "R2_module_is_validated_stage3":
            os.path.normcase(str(cfg_hist.get("local_decision_module_file", "")))
            == os.path.normcase(os.path.join(HERE, "candidate_decision.py")),
        "R2_frozen_prior": cand.get("predictor_frozen_prior"),
        # 规范化：predictor.describe() 用 "inherit_from_grid"，FREEZE.json 用
        # "inherit_from_safety_grid"，两者同义；r_range ↔ r_prior 同理。
        "R2_prior_matches_freeze": all(
            fr["frozen_model_spec"].get({"r_range": "r_prior"}.get(k, k))
            == (PRIOR_ALIASES.get(v, v) if isinstance(v, str) else v)
            for k, v in (cand.get("predictor_frozen_prior") or {}).items()),
        "R2_wiring_prior_spec_match":
            ((cand.get("provenance") or {}).get("frozen_model_spec") or {}).get("match"),
        "R2_provenance_all_match": cand.get("provenance_all_match"),
        "R2_candidate_file_hashes": {
            k: v["actual"][:16] for k, v in (cand.get("provenance") or {})
            .get("candidate_files", {}).items()},
        "R2_frozen_file_hashes": {
            k: v["actual"][:16] for k, v in (cand.get("provenance") or {})
            .get("frozen_baseline", {}).items()},
        "R2_decision_limits": cand.get("decision_limits"),
    }
    result["checks"]["A_decision_and_fingerprint"] = A
    print("\n" + "=" * 104)
    print("A. 实际调用的决策器、模型参数与模块指纹")
    print("=" * 104)
    for k, v in A.items():
        print(f"  {k:<34} = {v}")

    # ---------------- B. 真值隔离 ----------------
    static = wiring.check_truth_isolation()
    runtime = check_truth_isolation_runtime()
    B = {
        "candidate_ast_clean": static["clean"],
        "candidate_violations": static["violations"],
        "observation_keys_allowed": cand.get("observation_keys_allowed"),
        "http_driver_clean": runtime["clean"],
        "http_driver_fields": runtime["http_driver_fields"],
        "forbidden_attr_hits": runtime["forbidden_attr_hits"],
        "observer_wraps_http_driver": cand.get("observer_class"),
        "note": "observer 包在 HttpSimDriver 外层；HttpSimDriver 的重试在同一 request_id 内完成，"
                "对外部观测器只呈现一次调用，因此重试不会重复记入历史",
    }
    result["checks"]["B_truth_isolation"] = B
    print("\n" + "=" * 104)
    print("B. 候选是否已脱离本地真值访问")
    print("=" * 104)
    print(f"  候选模块 AST 静态检查:   {'通过' if static['clean'] else '违规'}")
    print(f"  观测字段白名单:          {B['observation_keys_allowed']}")
    print(f"  HttpSimDriver 字段:      {B['http_driver_fields']}")
    print(f"  接口层真值字段命中:      {B['forbidden_attr_hits'] or '无'}")
    print(f"  观测器位于接口层外层:    {B['observer_wraps_http_driver']}")

    # ---------------- C. 完整清除 / 结束证据 / 计费闭合 ----------------
    C = {}
    for tag in ("R1", "R2", "R3"):
        s = sessions.get(tag)
        if not s:
            C[tag] = {"present": False}
            continue
        comp, billing = s["completion"], s["billing"]
        evidence = s["per_channel_end_evidence"]
        decided = sum(1 for v in evidence.values()
                      if v["status"] in ("CLEARED", "ABSENT"))
        C[tag] = {
            "present": True,
            "completed_successfully": comp["completed_successfully"],
            "completion_status": comp["completion_status"],
            "cleared": comp["cleared_count"], "absent": comp["absent_count"],
            "unsolved": comp["unsolved_count"], "failed": comp["failed_count"],
            "n_channels_with_end_evidence": len(evidence),
            "n_channels_decided": decided,
            "all_channels_decided": decided == len(evidence) == 20,
            "T_virtual_s": billing["final_virtual_time_s"],
            "L_dist_m": billing["L_dist_m"], "M_measures": billing["M_measures"],
            "S_switches": billing["S_switches"],
            "F_clear_fail": billing["F_clear_fail"],
            "N_clear_succ": billing["N_clear_succ"],
            "closure_residual_s": billing["closure_residual_s"],
            "closure_ok": abs(billing["closure_residual_s"]) < 0.01,
            "unique_accepted_actions": billing["unique_accepted_action_count"],
            "real_time_s": comp["real_time_s"],
        }
    result["checks"]["C_completion_billing"] = C
    print("\n" + "=" * 104)
    print("C. 完整清除、逐频道结束证据、计费闭合")
    print("=" * 104)
    for tag, c in C.items():
        if not c.get("present"):
            print(f"  {tag}: 缺少会话文件")
            continue
        print(f"  {tag}: 完成={c['completed_successfully']} 清除={c['cleared']} "
              f"空频道={c['absent']} 未决={c['unsolved']} 失败={c['failed']} | "
              f"逐频道结束证据 {c['n_channels_decided']}/{c['n_channels_with_end_evidence']} "
              f"(全决={c['all_channels_decided']}) | "
              f"T={c['T_virtual_s']} 闭合残差={c['closure_residual_s']}s "
              f"闭合={c['closure_ok']} | 现实={c['real_time_s']}s")

    # ---------------- D. 接线前后决策一致 ----------------
    D = {"same_scenario": True}
    if by_tag["R2"].get("session_file"):
        jsonl = sessions["R2"]["http_session_file"]
        http_trace, n_unique = parse_http_trace(jsonl)
        from launch import HISTORY, run_case
        local = run_case(HISTORY, SCENARIO["mock_seed"], SCENARIO["sources"])
        loc_trace = [{"kind": r["kind"], "pos": [round(r["pos"][0], 2), round(r["pos"][1], 2)],
                      "channel": r["channel"], "result": r["result"]}
                     for r in local["action_trace"]]
        first_diff = None
        n = min(len(http_trace), len(loc_trace))
        for i in range(n):
            if http_trace[i] != loc_trace[i]:
                first_diff = {"index": i, "http": http_trace[i], "local": loc_trace[i]}
                break
        D = {
            "http_unique_requests": n_unique,
            "http_actions": len(http_trace),
            "local_actions": len(loc_trace),
            "same_length": len(http_trace) == len(loc_trace),
            "first_diff": first_diff,
            "identical": (len(http_trace) == len(loc_trace) and first_diff is None),
            "http_T": C.get("R2", {}).get("T_virtual_s"),
            "local_T": local["T_virtual_s"],
            "same_T": abs((C.get("R2", {}).get("T_virtual_s") or -1)
                          - local["T_virtual_s"]) < 0.01,
            "local_metrics": {k: local[k] for k in
                              ("T_virtual_s", "L_dist_m", "M_measures", "S_switches",
                               "F_clear_fail", "N_clear_succ", "cleared", "absent")},
        }
    result["checks"]["D_wiring_consistency"] = D
    print("\n" + "=" * 104)
    print("D. 接线前后在相同输入观测下的决策一致性")
    print("=" * 104)
    if "identical" in D:
        print(f"  HTTP 候选动作数={D['http_actions']}  本地候选动作数={D['local_actions']}  "
              f"长度相同={D['same_length']}")
        print(f"  逐动作完全一致 = {D['identical']}")
        print(f"  HTTP T={D['http_T']}  本地 T={D['local_T']}  相同={D['same_T']}")
        print(f"  本地候选分项: {D['local_metrics']}")
        if D["first_diff"]:
            print(f"  第一处差异 @ {D['first_diff']['index']}:")
            print(f"     http : {D['first_diff']['http']}")
            print(f"     local: {D['first_diff']['local']}")
    else:
        print("  缺少 R2 会话，无法比对")

    # ---------------- E. P3 既有入口配置不变 ----------------
    E = {"reference": P3_REFERENCE}
    if os.path.exists(P3_REFERENCE) and "R3" in sessions:
        with open(P3_REFERENCE, encoding="utf-8") as f:
            ref = json.load(f)
        ref_cfg = ref["effective_config"]
        now_cfg = sessions["R3"]["effective_config"]
        diffs = {k: {"reference": ref_cfg.get(k), "now": now_cfg.get(k)}
                 for k in CONFIG_KEYS if ref_cfg.get(k) != now_cfg.get(k)}
        E.update({
            "config_keys_compared": CONFIG_KEYS,
            "config_differences": diffs,
            "config_unchanged": len(diffs) == 0,
            "reference_fingerprint": ref.get("source_fingerprint"),
            "now_fingerprint": sessions["R3"]["source_fingerprint"],
        })
        E["fingerprint_changes"] = {
            k: {"reference": ref.get("source_fingerprint", {}).get(k),
                "now": sessions["R3"]["source_fingerprint"].get(k)}
            for k in sessions["R3"]["source_fingerprint"]
            if ref.get("source_fingerprint", {}).get(k)
            != sessions["R3"]["source_fingerprint"].get(k)}
    result["checks"]["E_p3_entry_unchanged"] = E
    print("\n" + "=" * 104)
    print("E. P3 既有入口配置是否保持不变")
    print("=" * 104)
    if E.get("config_keys_compared"):
        print(f"  比较的配置项: {E['config_keys_compared']}")
        print(f"  配置差异: {E['config_differences'] or '无'}")
        print(f"  配置保持不变 = {E['config_unchanged']}")
        print(f"  源码指纹变化（可能来自更早轮次，非本次接线）: {E['fingerprint_changes'] or '无'}")
    else:
        print("  缺少 P3 参照或 R3 会话")

    # ---------------- 总判定 ----------------
    all_ok = (
        A["R1_is_frozen_baseline"] and A["R2_is_candidate"]
        and A["R2_module_is_validated_stage3"] and A["R2_prior_matches_freeze"]
        and A["R2_provenance_all_match"]
        and B["candidate_ast_clean"] and B["http_driver_clean"]
        and all(C.get(t, {}).get("completed_successfully") for t in ("R1", "R2", "R3"))
        and all(C.get(t, {}).get("closure_ok") for t in ("R1", "R2", "R3"))
        and C["R2"]["all_channels_decided"]
        and D.get("identical") and D.get("same_T")
        and E.get("config_unchanged")
    )
    result["all_checks_pass"] = bool(all_ok)
    print("\n" + "=" * 104)
    print(f"总判定：{'全部通过' if all_ok else '存在未通过项，见上'}")
    print("=" * 104)

    out = os.path.join(OUT_DIR, "http_acceptance_summary.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"验收汇总 -> {out}")
    return result


if __name__ == "__main__":
    main()
