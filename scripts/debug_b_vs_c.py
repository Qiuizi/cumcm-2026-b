import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def compare():
    seed = 116
    env_b = SimEnvironment.generate_random_case(num_sources=16, is_p4=False, seed=seed)
    drv_b = LocalSimDriver(env_b)
    eng_b = StrategyEngine(driver=drv_b, is_p4=False, version="B", verbose=False)
    res_b = eng_b.execute()

    env_c = SimEnvironment.generate_random_case(num_sources=16, is_p4=False, seed=seed)
    drv_c = LocalSimDriver(env_c)
    eng_c = StrategyEngine(driver=drv_c, is_p4=False, version="C_BASELINE", verbose=False)
    res_c = eng_c.execute()

    print(f"B total dist: {env_b.total_distance_m:.1f}m | T: {res_b['virtual_time_s']:.1f}s | moves: {len(eng_b.movement_logs)}")
    print(f"C total dist: {env_c.total_distance_m:.1f}m | T: {res_c['virtual_time_s']:.1f}s | moves: {len(eng_c.movement_logs)}")

    print("\n--- B Movements ---")
    for m in eng_b.movement_logs:
        ch_str = f"ch={m['channel']}" if m['channel'] else ""
        print(f"B: {m['from']} -> {m['to']} | {m['dist_m']:6.1f}m | {m['purpose']:<16} {ch_str}")

    print("\n--- C Movements ---")
    for m in eng_c.movement_logs:
        ch_str = f"ch={m['channel']}" if m['channel'] else ""
        print(f"C: {m['from']} -> {m['to']} | {m['dist_m']:6.1f}m | {m['purpose']:<16} {ch_str}")

if __name__ == "__main__":
    compare()
