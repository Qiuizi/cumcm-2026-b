import sys
import os
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def test_compare_b_and_c():
    print("=" * 60)
    print("【问题三】同案例配对对比：版本 B (固定覆盖) vs 版本 C (滚动重排)")
    print("=" * 60)

    # 相同种子案例
    for n_src in [10, 13, 16]:
        print(f"\n>>> 案例规模: {n_src} 个干扰源 <<<")
        # 版本 B
        env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=100 + n_src)
        driver_b = LocalSimDriver(env_b)
        eng_b = StrategyEngine(driver=driver_b, is_p4=False, version="B", verbose=False)
        res_b = eng_b.execute()

        # 版本 C
        env_c = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=100 + n_src)
        driver_c = LocalSimDriver(env_c)
        eng_c = StrategyEngine(driver=driver_c, is_p4=False, version="C", verbose=False)
        res_c = eng_c.execute()

        print(f"【版本 B】清除数: {res_b['cleared_count']}/{n_src}, 虚拟总时间 T: {res_b['virtual_time_s']:.1f}s, 移动路程: {env_b.total_distance_m:.1f}m, 真实耗时: {res_b['real_time_s']:.2f}s, 平均单目标耗时: {res_b['avg_time_per_target']:.1f}s")
        print(f"【版本 C】清除数: {res_c['cleared_count']}/{n_src}, 虚拟总时间 T: {res_c['virtual_time_s']:.1f}s, 移动路程: {env_c.total_distance_m:.1f}m, 真实耗时: {res_c['real_time_s']:.2f}s, 平均单目标耗时: {res_c['avg_time_per_target']:.1f}s")
        diff_t = res_b['virtual_time_s'] - res_c['virtual_time_s']
        print(f"--> 版本 C 相比版本 B 节省虚拟时间: {diff_t:.1f}s ({diff_t/res_b['virtual_time_s']*100:.1f}%)")

if __name__ == "__main__":
    test_compare_b_and_c()
