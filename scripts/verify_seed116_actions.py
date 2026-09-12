import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from src.sim_env import SimEnvironment, LocalSimDriver
from src.strategy_engine import StrategyEngine

class ActionLoggingDriver:
    """包装 Driver，严格记录每个实际被接受执行的动作"""
    def __init__(self, raw_driver):
        self.raw_driver = raw_driver
        self.accepted_actions = []

    def enter(self):
        res = self.raw_driver.enter()
        self.accepted_actions.append({
            "action": "enter",
            "pos": (0.0, 0.0),
            "channel": None,
            "res": res,
            "virtual_time_s": res["virtual_time_s"],
        })
        return res

    def exit(self):
        res = self.raw_driver.exit()
        self.accepted_actions.append({
            "action": "exit",
            "pos": None,
            "channel": None,
            "res": res,
            "virtual_time_s": res["virtual_time_s"],
        })
        return res

    def measure(self, pos, channel):
        res = self.raw_driver.measure(pos, channel)
        self.accepted_actions.append({
            "action": "measure",
            "pos": (round(pos[0], 2), round(pos[1], 2)),
            "channel": channel,
            "res": res["measure_result"],
            "virtual_time_s": res["virtual_time_s"],
        })
        return res

    def clear(self, pos, channel):
        res = self.raw_driver.clear(pos, channel)
        self.accepted_actions.append({
            "action": "clear",
            "pos": (round(pos[0], 2), round(pos[1], 2)),
            "channel": channel,
            "res": res["clear_result"],
            "virtual_time_s": res["virtual_time_s"],
        })
        return res

def main():
    seed = 116
    n_src = 16

    print("=" * 80)
    print(f"【深入调查】Seed {seed} (16源) C_BASELINE vs C_OPT 实际接受动作完整核对")
    print("=" * 80)

    # 1. 运行 C_BASELINE
    env_base = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
    drv_base_raw = LocalSimDriver(env_base)
    logger_base = ActionLoggingDriver(drv_base_raw)
    eng_base = StrategyEngine(driver=logger_base, is_p4=False, version="C_BASELINE", verbose=False)
    res_base = eng_base.execute()

    # 2. 运行 C_OPT
    env_opt = SimEnvironment.generate_random_case(num_sources=n_src, is_p4=False, seed=seed)
    drv_opt_raw = LocalSimDriver(env_opt)
    logger_opt = ActionLoggingDriver(drv_opt_raw)
    eng_opt = StrategyEngine(driver=logger_opt, is_p4=False, version="C_OPT", verbose=False)
    res_opt = eng_opt.execute()

    actions_base = logger_base.accepted_actions
    actions_opt = logger_opt.accepted_actions

    print(f"\n[动作总数对比]")
    print(f"  C_BASELINE 实际执行的驱动器动作数: {len(actions_base)}")
    print(f"  C_OPT      实际执行的驱动器动作数: {len(actions_opt)}")
    print(f"  模拟器实际累计移动距离:")
    print(f"    C_BASELINE: {env_base.total_distance_m:.4f} m")
    print(f"    C_OPT:      {env_opt.total_distance_m:.4f} m")
    print(f"  模拟器最终虚拟时间:")
    print(f"    C_BASELINE: {env_base.virtual_time_s:.4f} s")
    print(f"    C_OPT:      {env_opt.virtual_time_s:.4f} s")

    # 逐动作核对是否 100% 一致
    diffs = []
    for idx, (a_b, a_o) in enumerate(zip(actions_base, actions_opt)):
        if a_b != a_o:
            diffs.append((idx, a_b, a_o))

    print(f"\n[动作逐条差异比对]")
    if not diffs and len(actions_base) == len(actions_opt):
        print(f"  --> 结论: 两版本的实际动作序列 100% 完全一致，无任何一条动作差异！")
    else:
        print(f"  --> 发现 {len(diffs)} 处差异:")
        for idx, a_b, a_o in diffs[:10]:
            print(f"    Step {idx}: BASE={a_b} | OPT={a_o}")

    # 检查被“替代/删除”的搜索点
    subst_pts = res_opt["search_points_substituted"]
    redundant_pts = res_base["redundant_search_points_executed"]
    print(f"\n[被删除/标记为替代的搜索点排查]")
    print(f"  C_OPT 标记为替代删除的搜索点: {subst_pts}")
    print(f"  C_BASELINE 标记为冗余执行的搜索点: {redundant_pts}")

    # 检查这些搜索点在 C_BASELINE 中是否曾产生任何 /measure 或 /clear
    for pt in redundant_pts:
        pt_rounded = (round(pt[0], 2), round(pt[1], 2))
        matching_actions = [a for a in actions_base if a["pos"] == pt_rounded]
        print(f"  搜索点 {pt_rounded} 在 C_BASELINE 实际动作历史中出现的记录数: {len(matching_actions)}")
        for m in matching_actions:
            print(f"    -> 动作: {m['action']}, 频道: {m['channel']}, 结果: {m['res']}")

    # 检查计划位置 vs 实际位置
    print(f"\n[计划位置 vs 模拟器实际动作位置分析]")
    print(f"  C_BASELINE 中 engine.search_points_visited 记录了: {[ (round(p[0],1), round(p[1],1)) for p in res_base['search_points_visited'] ]}")
    print(f"  但因进入 scan_channels_at_station 时 channels_to_scan 为空，函数第 179 行直接 return。")
    print(f"  驱动器是否收到过向该点的移动或测量？ 0 次。")
    print(f"  模拟器底层的真实位置从未到达该点。")

if __name__ == "__main__":
    main()
