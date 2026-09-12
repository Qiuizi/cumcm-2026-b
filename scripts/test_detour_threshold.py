import os
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def test_variants():
    groups = [10, 13, 16]
    for n_src in groups:
        seed = 100 + n_src
        print(f"\n==================== n_src = {n_src} (seed {seed}) ====================")
        
        # B
        env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_b = LocalSimDriver(env_b)
        eng_b = StrategyEngine(driver=drv_b, is_p4=False, version="B", verbose=False)
        res_b = eng_b.execute()

        # C_BASELINE
        env_base = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_base = LocalSimDriver(env_base)
        eng_base = StrategyEngine(driver=drv_base, is_p4=False, version="C_BASELINE", verbose=False)
        res_base = eng_base.execute()

        # Variant: Smart Route Sharing
        # 1. Prune redundant search points (0 utility or K>=16 or all resolved)
        # 2. When building open route:
        #    If found_channels is non-empty:
        #    Only include search points that are on the way (detour <= max_detour), or prioritize targets
        for max_detour in [100.0, 200.0, 300.0, 500.0, 1e9]:
            env_v = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
            drv_v = LocalSimDriver(env_v)
            eng_v = StrategyEngine(driver=drv_v, is_p4=False, version="C", verbose=False)

            def make_runner(max_d, engine):
                def run_v():
                    engine.scan_channels_at_station((0.0, 0.0))
                    engine.prune_redundant_search_points()

                    while not engine.check_completion():
                        engine.prune_redundant_search_points()
                        found_channels = [c for c, st in engine.channels.items() if st.status == "FOUND"]

                        if not found_channels and not engine.remaining_search_points:
                            break

                        tasks = []
                        for ch in found_channels:
                            cells = engine.channels[ch].grid.get_surviving_cells()
                            rep_pos = np.mean(cells, axis=0) if len(cells) > 0 else engine.cur_pos
                            tasks.append({"type": "target", "channel": ch, "pos": (float(rep_pos[0]), float(rep_pos[1]))})

                        # If no found channels, must use search points
                        if not found_channels:
                            for idx, pt in enumerate(engine.remaining_search_points):
                                tasks.append({"type": "search", "point_idx": idx, "pos": pt})
                        else:
                            # If found channels exist, only include search points whose distance to nearest target or cur_pos is reasonable
                            cur = np.array(engine.cur_pos)
                            for idx, pt in enumerate(engine.remaining_search_points):
                                pt_arr = np.array(pt)
                                # Check min detour between cur and any target
                                min_detour = 1e9
                                for t in tasks:
                                    t_pos = np.array(t["pos"])
                                    detour = np.linalg.norm(cur - pt_arr) + np.linalg.norm(pt_arr - t_pos) - np.linalg.norm(cur - t_pos)
                                    if detour < min_detour:
                                        min_detour = detour
                                if min_detour <= max_d:
                                    tasks.append({"type": "search", "point_idx": idx, "pos": pt})

                        if not tasks:
                            break

                        if len(tasks) == 1:
                            best_task = tasks[0]
                        else:
                            cur = np.array(engine.cur_pos)
                            unvisited = list(range(len(tasks)))
                            first_idx = min(unvisited, key=lambda i: np.linalg.norm(np.array(tasks[i]["pos"]) - cur))
                            path = [first_idx]
                            unvisited.remove(first_idx)
                            while unvisited:
                                best_candidate, best_insert_pos, best_cost = None, None, 1e9
                                for cand in unvisited:
                                    cand_pos = np.array(tasks[cand]["pos"])
                                    c_head = np.linalg.norm(cand_pos - cur) + np.linalg.norm(np.array(tasks[path[0]]["pos"]) - cand_pos) - np.linalg.norm(np.array(tasks[path[0]]["pos"]) - cur)
                                    if c_head < best_cost:
                                        best_cost, best_candidate, best_insert_pos = c_head, cand, 0
                                    for p in range(len(path) - 1):
                                        p1_p, p2_p = np.array(tasks[path[p]]["pos"]), np.array(tasks[path[p+1]]["pos"])
                                        c_mid = np.linalg.norm(p1_p - cand_pos) + np.linalg.norm(cand_pos - p2_p) - np.linalg.norm(p1_p - p2_p)
                                        if c_mid < best_cost:
                                            best_cost, best_candidate, best_insert_pos = c_mid, cand, p + 1
                                    p_tail = np.array(tasks[path[-1]]["pos"])
                                    c_tail = np.linalg.norm(cand_pos - p_tail)
                                    if c_tail < best_cost:
                                        best_cost, best_candidate, best_insert_pos = c_tail, cand, len(path)
                                path.insert(best_insert_pos, best_candidate)
                                unvisited.remove(best_candidate)
                            best_task = tasks[path[0]]

                        if best_task["type"] == "target":
                            engine.service_found_target(best_task["channel"])
                        else:
                            pt = best_task["pos"]
                            engine.remaining_search_points.remove(pt)
                            engine.search_points_visited.append(pt)
                            engine.scan_channels_at_station(pt)
                            engine.prune_redundant_search_points()

                return run_v

            eng_v.run_version_c_openroute = make_runner(max_detour, eng_v)
            res_v = eng_v.execute()
            label = f"max_detour={max_detour:5.0f}m" if max_detour < 1e8 else "max_detour=  INF"
            print(f"  {label}: T={res_v['virtual_time_s']:7.1f}s | SP visit={res_v['search_points_visited_count']}/7 | SP subst={res_v['search_points_substituted_count']} | Cleared={res_v['cleared_count']}")

        print(f"  Version B:       T={res_b['virtual_time_s']:7.1f}s")
        print(f"  Version C_BASE:  T={res_base['virtual_time_s']:7.1f}s")

if __name__ == "__main__":
    test_variants()
