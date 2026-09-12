import os
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def run_paired_test():
    print("=" * 75, flush=True)
    print("【问题三】基线 (C_BASELINE) 与 优化版 (C_OPT) 同场景配对评估与官方案例检验", flush=True)
    print("=" * 75, flush=True)

    # 涵盖快速测试种子与官方基准种子
    test_cases = [
        ("P3-10src (seed 110)", 10, 110),
        ("P3-13src (seed 113)", 13, 113),
        ("P3-16src (seed 116)", 16, 116),
        ("P3-10src (benchmark 4000)", 10, 4000),
        ("P3-13src (benchmark 4300)", 13, 4300),
        ("P3-16src (benchmark 4600)", 16, 4600),
    ]

    for name, n_src, seed in test_cases:
        print(f"\n>>> 测试案例: {name} <<<", flush=True)

        # 1. 基线版本 B
        env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_b = LocalSimDriver(env_b)
        eng_b = StrategyEngine(driver=drv_b, is_p4=False, version="B", verbose=False)
        res_b = eng_b.execute()

        # 2. 当前基线版本 C_BASELINE (无剪枝)
        env_base = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_base = LocalSimDriver(env_base)
        eng_base = StrategyEngine(driver=drv_base, is_p4=False, version="C_BASELINE", verbose=False)
        res_base = eng_base.execute()

        # 3. 优化版本 C_OPT (动态替代剪枝与共用覆盖)
        env_opt = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_opt = LocalSimDriver(env_opt)
        eng_opt = StrategyEngine(driver=drv_opt, is_p4=False, version="C_OPT", verbose=False)
        res_opt = eng_opt.execute()

        tb = res_b["virtual_time_s"]
        t_base = res_base["virtual_time_s"]
        t_opt = res_opt["virtual_time_s"]
        save_vs_base = t_base - t_opt
        save_vs_b = tb - t_opt

        print(f"  版本 B (固定基线):       T = {tb:7.1f}s | 清除: {res_b['cleared_count']}/{n_src} | 移动路程: {env_b.total_distance_m:7.1f}m", flush=True)
        print(f"  版本 C_BASELINE (原方案): T = {t_base:7.1f}s | 清除: {res_base['cleared_count']}/{n_src} | 访问搜索点: {res_base['search_points_visited_count']}/7 | 冗余执行: {res_base['redundant_search_points_executed_count']} 个", flush=True)
        print(f"  版本 C_OPT (优化版):      T = {t_opt:7.1f}s | 清除: {res_opt['cleared_count']}/{n_src} | 访问搜索点: {res_opt['search_points_visited_count']}/7 | 动态替代: {res_opt['search_points_substituted_count']} 个", flush=True)
        print(f"  --> 优化版本相对 C_BASELINE 净节省: {save_vs_base:+6.1f}s ({save_vs_base/t_base*100:+.2f}%)", flush=True)
        print(f"  --> 优化版本相对 版本 B    净节省: {save_vs_b:+6.1f}s ({save_vs_b/tb*100:+.2f}%)", flush=True)
        if res_base['redundant_search_points_executed']:
            pts_str = [f"({p[0]:.1f}, {p[1]:.1f})" for p in res_base['redundant_search_points_executed']]
            print(f"  [核查实证] C_BASELINE 执行的零增益冗余搜索点: {pts_str}", flush=True)
        if res_opt['search_points_substituted']:
            pts_str = [f"({p[0]:.1f}, {p[1]:.1f})" for p in res_opt['search_points_substituted']]
            print(f"  [优化确认] C_OPT 成功识别并动态替代免跑的搜索点: {pts_str}", flush=True)

if __name__ == "__main__":
    run_paired_test()
