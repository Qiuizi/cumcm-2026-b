import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def run_cost_closure_audit():
    test_cases = [
        ("P3-10src (seed 110)", 10, 110),
        ("P3-13src (seed 113)", 13, 113),
        ("P3-16src (seed 116)", 16, 116),
        ("P3-10src (benchmark 4000)", 10, 4000),
        ("P3-13src (benchmark 4300)", 13, 4300),
        ("P3-16src (benchmark 4600)", 16, 4600),
    ]

    print("=" * 125)
    print("【五类成本完整闭合审计表】移动 + 切频 + 检测 + 失败清除 + 成功清除 = 总虚拟时间 T")
    print("=" * 125)

    header = f"{'案例名称':<26} | {'开关':<4} | {'移动耗时':<9} | {'切频耗时':<9} | {'检测耗时':<9} | {'失败清除':<12} | {'成功清除':<12} | {'五类求和':<9} | {'总时间T':<9} | {'闭合残差':<7}"
    print(header)
    print("-" * 125)

    all_rows = []

    for name, n_src, seed in test_cases:
        for sw, sw_name in [(True, "ON"), (False, "OFF")]:
            env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
            drv = LocalSimDriver(env)
            eng = StrategyEngine(driver=drv, is_p4=False, version="C", scan_at_clearance=sw, verbose=False)
            res = eng.execute()

            t_move = env.total_distance_m / 5.0
            t_switch = 1.0 * env.switch_count
            t_meas = 5.0 * env.measure_count
            t_fail = 3.0 * env.clear_fail_count
            t_succ = 5.0 * env.clear_succ_count
            t_sum = t_move + t_switch + t_meas + t_fail + t_succ
            t_tot = env.virtual_time_s
            residual = abs(t_tot - t_sum)

            fail_str = f"{env.clear_fail_count}次/{t_fail:.1f}s"
            succ_str = f"{env.clear_succ_count}次/{t_succ:.1f}s"

            print(f"{name if sw_name == 'ON' else '':<26} | {sw_name:<4} | {t_move:9.2f} | {t_switch:9.2f} | {t_meas:9.2f} | {fail_str:<12} | {succ_str:<12} | {t_sum:9.2f} | {t_tot:9.2f} | {residual:7.4f}")

            all_rows.append({
                "name": name,
                "sw": sw_name,
                "n_src": n_src,
                "t_move": t_move,
                "n_switch": env.switch_count,
                "t_switch": t_switch,
                "n_meas": env.measure_count,
                "t_meas": t_meas,
                "n_fail": env.clear_fail_count,
                "t_fail": t_fail,
                "n_succ": env.clear_succ_count,
                "t_succ": t_succ,
                "t_sum": t_sum,
                "t_tot": t_tot,
                "residual": residual,
            })
        print("-" * 125)

if __name__ == "__main__":
    run_cost_closure_audit()
