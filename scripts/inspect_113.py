import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def inspect():
    seed = 113
    env_base = SimEnvironment.generate_random_case(num_sources=13, is_p4=False, seed=seed)
    drv_base = LocalSimDriver(env_base)
    eng_base = StrategyEngine(driver=drv_base, is_p4=False, version="C_BASELINE", verbose=False)
    res_base = eng_base.execute()

    print(f"Seed 113 C_BASELINE: T={res_base['virtual_time_s']:.1f}s, dist={env_base.total_distance_m:.1f}m")
    for m in eng_base.movement_logs:
        ch_str = f"ch={m['channel']}" if m['channel'] else ""
        print(f"  {m['purpose']:<18} {m['from']} -> {m['to']} | {m['dist_m']:6.1f}m {ch_str} | vt={m['virtual_time_s']}")

if __name__ == "__main__":
    inspect()
