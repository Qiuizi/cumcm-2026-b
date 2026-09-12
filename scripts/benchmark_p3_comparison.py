import os
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def benchmark():
    groups = [10, 13, 16]
    n_cases = 3  # 3 cases per group for fast reliable check

    print("=" * 75)
    print("【问题三】全案例配对基准测试：版本 B vs C_BASELINE vs C_OPT (路线共用)")
    print("=" * 75)

    results = []

    for n_src in groups:
        print(f"\n>>> 评测源数量: {n_src} 个 <<<")
        for i in range(n_cases):
            seed = 3000 + n_src * 100 + i
            case_id = f"P3-{n_src}src-case{i+1}"

            # 1. Version B
            env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
            drv_b = LocalSimDriver(env_b)
            eng_b = StrategyEngine(driver=drv_b, is_p4=False, version="B", verbose=False)
            res_b = eng_b.execute()

            # 2. Version C_BASELINE
            env_base = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
            drv_base = LocalSimDriver(env_base)
            eng_base = StrategyEngine(driver=drv_base, is_p4=False, version="C_BASELINE", verbose=False)
            res_base = eng_base.execute()

            # 3. Version C_OPT
            env_opt = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
            drv_opt = LocalSimDriver(env_opt)
            eng_opt = StrategyEngine(driver=drv_opt, is_p4=False, version="C_OPT", verbose=False)
            res_opt = eng_opt.execute()

            rec = {
                "case_id": case_id,
                "sources": n_src,
                "t_b": res_b["virtual_time_s"],
                "t_base": res_base["virtual_time_s"],
                "t_opt": res_opt["virtual_time_s"],
                "base_sp_visit": res_base["search_points_visited_count"],
                "base_sp_redundant": res_base["redundant_search_points_executed_count"],
                "opt_sp_visit": res_opt["search_points_visited_count"],
                "opt_sp_subst": res_opt["search_points_substituted_count"],
                "clear_opt": res_opt["cleared_count"],
            }
            results.append(rec)
            save_vs_base = rec["t_base"] - rec["t_opt"]
            save_vs_b = rec["t_b"] - rec["t_opt"]
            print(f"  [{case_id}] B: {rec['t_b']:6.1f}s | C_BASE: {rec['t_base']:6.1f}s (SP冗余:{rec['base_sp_redundant']}) | C_OPT: {rec['t_opt']:6.1f}s (SP替代:{rec['opt_sp_subst']}) | 省时vs基线: {save_vs_base:+6.1f}s")

    print("\n" + "=" * 75)
    print("【测试统计汇总】")
    print("=" * 75)
    mean_tb = np.mean([r["t_b"] for r in results])
    mean_tbase = np.mean([r["t_base"] for r in results])
    mean_topt = np.mean([r["t_opt"] for r in results])
    tot_subst = sum(r["opt_sp_subst"] for r in results)
    tot_redundant = sum(r["base_sp_redundant"] for r in results)

    print(f"版本 B 平均虚拟耗时:          {mean_tb:.2f} 秒")
    print(f"版本 C_BASELINE 平均虚拟耗时:  {mean_tbase:.2f} 秒 (累计冗余执行搜索点: {tot_redundant} 次)")
    print(f"版本 C_OPT 平均虚拟耗时:       {mean_topt:.2f} 秒 (累计替代免跑搜索点: {tot_subst} 次)")
    print(f"C_OPT 相对 C_BASELINE 净节省: {mean_tbase - mean_topt:+.2f} 秒 ({(mean_tbase - mean_topt)/mean_tbase*100:+.2f}%)")
    print(f"C_OPT 相对 版本 B 净节省:      {mean_tb - mean_topt:+.2f} 秒 ({(mean_tb - mean_topt)/mean_tb*100:+.2f}%)")
    print("=" * 75)

if __name__ == "__main__":
    benchmark()
