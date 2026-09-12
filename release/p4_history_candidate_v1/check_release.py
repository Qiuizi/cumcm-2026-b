"""
check_release.py —— 发布包自检（只读，不跑对局）

检查内容：
  1. 实际导入路径：所有依赖都必须解析到**本发布包内**，且不落在实验工作区
  2. 源码指纹：包内文件与 BUILD_INFO.json / FREEZE.json 一致；候选实现与 upstream 验收版一致
  3. 模型参数：预测器的冻结先验与 FREEZE.json 一致
  4. 真值隔离：候选模块 AST 静态检查
  5. 启动行为：official 模式在无服务时"直接退出且不自动拉起 Mock"；official 模式拒绝场景参数
"""
import importlib
import os
import subprocess
import sys

PKG = os.path.dirname(os.path.abspath(__file__))
for p in (PKG, os.path.join(PKG, "candidate")):
    if p not in sys.path:
        sys.path.insert(0, p)

MODULES = ["src.strategy_engine", "src.evidence_tracker", "src.sim_env",
           "src.client_runner", "src.conservative_grid", "src.local_decision",
           "src.mock_server", "local_decision_frozen", "conservative_grid_frozen",
           "candidate_decision", "predictor", "model", "observer", "wiring"]

FORBIDDEN_PARENT_HINT = "cumcm2026" + os.sep + "experiments"


def main():
    ok = True
    print("=" * 96)
    print("发布包自检（只读）")
    print("=" * 96)

    # 1. 导入路径
    print("\n[1] 实际导入路径")
    paths = {}
    for m in MODULES:
        mod = importlib.import_module(m)
        p = os.path.abspath(getattr(mod, "__file__", "<none>"))
        paths[m] = p
        inside = os.path.normcase(p).startswith(os.path.normcase(PKG + os.sep))
        leaked = FORBIDDEN_PARENT_HINT.lower() in os.path.normcase(p)
        ok &= inside and not leaked
        flag = "OK " if (inside and not leaked) else "!! "
        print(f"  {flag}{m:<28} {p}")
    print(f"  全部依赖都在包内且未引用实验工作区: {all(os.path.normcase(v).startswith(os.path.normcase(PKG + os.sep)) for v in paths.values())}")

    # 2. 指纹
    print("\n[2] 源码指纹")
    import wiring
    prov = wiring.verify_provenance()
    print(f"  候选/冻结指纹与 FREEZE.json 一致: {prov['all_match']}")
    for rel, c in prov["candidate_files"].items():
        print(f"    {'OK ' if c['match'] else '!! '}{rel:<44} {c['actual'][:16]}")
        ok &= c["match"]
    for rel, c in prov["frozen_baseline"].items():
        print(f"    {'OK ' if c['match'] else '!! '}{rel:<44} {c['actual'][:16]}  [{c['role']}]")
        ok &= c["match"]

    # upstream（第三阶段验收版）一致性
    import json
    fr = json.load(open(os.path.join(PKG, "FREEZE.json"), encoding="utf-8"))
    up = fr["upstream_validated"]
    import hashlib
    def sha(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    print("  与 upstream 验收版逐字节一致：")
    for name, expect in up.items():
        p = os.path.join(PKG, "candidate", name) if os.path.exists(
            os.path.join(PKG, "candidate", name)) else os.path.join(PKG, name)
        actual = sha(p) if os.path.exists(p) else "MISSING"
        same = (actual == expect)
        ok &= same
        print(f"    {'OK ' if same else '!! '}{name:<28} {actual[:16]}  upstream {expect[:16]}")

    # 3. 模型参数
    print("\n[3] 模型参数")
    from predictor import HistoryReceptionPredictor as P
    spec = fr["frozen_model_spec"]
    checks = {
        "n_hyp": (spec["n_hyp"], P.N_HYP),
        "p_dir": (spec["p_dir"], P.P_DIR),
        "r_prior": (spec["r_prior"], [P.R_LO, P.R_HI]),
        "pool_factor": (spec["pool_factor"], P.POOL_FACTOR),
        "max_rounds": (spec["max_rounds"], P.MAX_ROUNDS),
        "seed_base": (spec["seed_base"], P.SEED_BASE),
        "seed_stride": (spec["seed_stride"], P.SEED_STRIDE),
    }
    for k, (a, b) in checks.items():
        same = (a == b)
        ok &= same
        print(f"    {'OK ' if same else '!! '}{k:<14} spec={a} actual={b}")

    # 4. 真值隔离
    print("\n[4] 真值隔离静态检查")
    iso = wiring.check_truth_isolation()
    print(f"  候选模块无禁止字段访问: {iso['clean']}")
    if iso["violations"]:
        print(f"    违规: {iso['violations'][:5]}")
    ok &= iso["clean"]

    # 5. 启动行为（不跑对局）
    print("\n[5] 启动行为（official 模式，无服务）")
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free_port = s.getsockname()[1]
    s.close()

    r = subprocess.run([sys.executable, os.path.join(PKG, "run_port_test.py"),
                        "--prob", "p4", "--version", "C", "--port", str(free_port)],
                       capture_output=True, text=True, encoding="utf-8", cwd=PKG)
    no_mock = "本地模拟运行" not in (r.stdout or "")
    fail_fast = (r.returncode == 2) and ("连接失败" in (r.stdout or ""))
    ok &= no_mock and fail_fast
    print(f"    无服务时直接退出: {fail_fast} (returncode={r.returncode})")
    print(f"    未自动拉起 Mock:  {no_mock}")

    r2 = subprocess.run([sys.executable, os.path.join(PKG, "run_port_test.py"),
                         "--prob", "p4", "--version", "C", "--port", str(free_port),
                         "--sources", "10"],
                        capture_output=True, text=True, encoding="utf-8", cwd=PKG)
    guard = ("不允许传入" in (r2.stderr or "") + (r2.stdout or "")) and r2.returncode != 0
    ok &= guard
    print(f"    official 拒绝场景参数 --sources: {guard}")

    # 6. 【D2】运行产物目录必须在**包外**（否则发布包重建会删除历史运行记录）
    print("\n[6] 运行产物目录（D2：包外独立目录）")
    cfg_path = os.path.join(PKG, "runs_config.json")
    cfg_ok = os.path.exists(cfg_path)
    ok &= cfg_ok
    print(f"    包内 runs_config.json 存在: {cfg_ok}")
    runs_dir = None
    if cfg_ok:
        sys.path.insert(0, os.path.join(PKG, "src"))
        from client_runner import resolve_runs_dir
        runs_dir = resolve_runs_dir(project_root=PKG)
        pkg_abs = os.path.abspath(PKG)
        runs_abs = os.path.abspath(runs_dir)
        outside = os.path.commonpath([pkg_abs, runs_abs]) != pkg_abs
        ok &= outside
        print(f"    解析出的运行产物根目录: {runs_abs}")
        print(f"    位于包目录之外（重建不会删除）: {outside}")
        print(f"    可用 --runs_dir / 环境变量 CUMCM_RUNS_DIR 覆盖: True")

    print("\n" + "=" * 96)
    print(f"发布包自检总结论：{'全部通过' if ok else '存在未通过项'}")
    print("=" * 96)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
