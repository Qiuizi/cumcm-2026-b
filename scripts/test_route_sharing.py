import os
import sys
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

def test_idea():
    print("=" * 70)
    print("【测试路线共用与搜索优先权】对比当前 C vs 路线共用版 C_shared")
    print("=" * 70)

    for n_src in [10, 13, 16]:
        seed = 100 + n_src
        print(f"\n>>> 干扰源数: {n_src} 个 (种子 {seed}) <<<")

        # 1. 基线 B
        env_b = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_b = LocalSimDriver(env_b)
        eng_b = StrategyEngine(driver=drv_b, is_p4=False, version="B", verbose=False)
        res_b = eng_b.execute()

        # 2. 当前基线 C_BASELINE
        env_base = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_base = LocalSimDriver(env_base)
        eng_base = StrategyEngine(driver=drv_base, is_p4=False, version="C_BASELINE", verbose=False)
        res_base = eng_base.execute()

        # 3. 路线共用版 C_shared: 目标优先服务，利用清除点共用覆盖，仅在无 FOUND 时才出动搜索点
        env_sh = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
        drv_sh = LocalSimDriver(env_sh)
        eng_sh = StrategyEngine(driver=drv_sh, is_p4=False, version="C", verbose=False)

        # 重载 run_version_c_openroute 为真正共用覆盖路线
        def run_c_shared(engine):
            engine.scan_channels_at_station((0.0, 0.0))
            engine.prune_redundant_search_points()

            while not engine.check_completion():
                engine.prune_redundant_search_points()
                found_channels = [c for c, st in engine.channels.items() if st.status == "FOUND"]

                if found_channels:
                    # 有已发现目标：在所有 FOUND 目标间规划 2-Opt 开放最优路线！
                    tasks = []
                    for ch in found_channels:
                        cells = engine.channels[ch].grid.get_surviving_cells()
                        rep_pos = np.mean(cells, axis=0) if len(cells) > 0 else engine.cur_pos
                        tasks.append({
                            "type": "target",
                            "channel": ch,
                            "pos": (float(rep_pos[0]), float(rep_pos[1])),
                        })

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

                    ch = best_task["channel"]
                    engine.service_found_target(ch)

                elif engine.remaining_search_points:
                    # 无已发现目标：前往离当前位置最近的有效搜索点
                    cur = np.array(engine.cur_pos)
                    best_pt = min(engine.remaining_search_points, key=lambda p: np.linalg.norm(np.array(p) - cur))
                    engine.remaining_search_points.remove(best_pt)
                    engine.search_points_visited.append(best_pt)
                    engine.scan_channels_at_station(best_pt)
                    engine.prune_redundant_search_points()
                else:
                    break

        eng_sh.run_version_c_openroute = lambda: run_c_shared(eng_sh)
        res_sh = eng_sh.execute()

        print(f"  版本 B:          T = {res_b['virtual_time_s']:7.1f}s | 清除: {res_b['cleared_count']}/{n_src} | 移动: {env_b.total_distance_m:7.1f}m")
        print(f"  版本 C_BASELINE: T = {res_base['virtual_time_s']:7.1f}s | 清除: {res_base['cleared_count']}/{n_src} | 移动: {env_base.total_distance_m:7.1f}m | SP访问: {res_base['search_points_visited_count']}/7")
        print(f"  版本 C_shared:   T = {res_sh['virtual_time_s']:7.1f}s | 清除: {res_sh['cleared_count']}/{n_src} | 移动: {env_sh.total_distance_m:7.1f}m | SP访问: {res_sh['search_points_visited_count']}/7 | SP替代: {res_sh['search_points_substituted_count']}")
        print(f"  --> C_shared 相对 C_BASELINE 节省: {res_base['virtual_time_s'] - res_sh['virtual_time_s']:+.1f}s")
        print(f"  --> C_shared 相对 版本 B    节省: {res_b['virtual_time_s'] - res_sh['virtual_time_s']:+.1f}s")

if __name__ == "__main__":
    test_idea()
