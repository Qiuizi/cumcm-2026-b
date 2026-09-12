import os
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def analyze():
    for n_src in [10, 13, 16]:
        seed = 100 + n_src
        env = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv = LocalSimDriver(env)
        eng = StrategyEngine(driver=drv, is_p4=False, version="C", verbose=False)
        
        # hook scan_channels_at_station to log details
        old_scan = eng.scan_channels_at_station
        scan_records = []
        def hooked_scan(pos):
            # check which channels will be scanned
            ch_list = []
            for ch in range(1, 21):
                if eng.channels[ch].status == "UNKNOWN" and eng.evidence_tracker.can_eliminate_any_cell(pos, ch):
                    ch_list.append(ch)
            scan_records.append({
                "vt": eng.virtual_time_s,
                "pos": pos,
                "channels_count": len(ch_list),
                "channels": ch_list,
                "is_sp": any(math.hypot(pos[0]-sp[0], pos[1]-sp[1]) < 1.0 for sp in eng.evidence_tracker.search_points),
            })
            return old_scan(pos)
        import math
        eng.scan_channels_at_station = hooked_scan
        
        res = eng.execute()
        print("=" * 60)
        print(f"CASE {n_src} sources (seed {seed}):")
        print(f"T={res['virtual_time_s']:.1f}s, cleared={res['cleared_count']}, absent={res['absent_count']}")
        print("Station scan history:")
        for r in scan_records:
            print(f"  VT {r['vt']:8.1f}s | pos=({r['pos'][0]:7.1f}, {r['pos'][1]:7.1f}) | is_SP={r['is_sp']} | scan_count={r['channels_count']} channels: {r['channels']}")


if __name__ == "__main__":
    analyze()
