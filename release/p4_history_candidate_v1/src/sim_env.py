"""
sim_env.py - 高保真物理仿真参考环境
严格遵循赛题及附件1、附件2规定：
1. 目标分布在 Omega = B((0,0), 1800) 内
2. 频道 1-20，源数量 10-16 个，每频道最多 1 个源
3. 有效接收半径 R 独立位于 [1000, 1500] 米
4. 全向与定向源 (定向源发射角两侧各 90 度，即前向半平面)
5. 测向误差 [-1°, 1°]，同地点固定
6. near: 距离 <= 5m 返回 near (无示向度)
7. clear: 距离 <= 20m 成功 (5s)，否则失败 (3s)
8. 虚拟时钟精密累加: T = L/5 + N_switch + 5*N_measure + 3*N_clear_fail + 5*N_clear_succ
"""

import math
import hashlib
import numpy as np


class RadioSource:
    def __init__(
        self,
        channel: int,
        x: float,
        y: float,
        R: float,
        is_directional: bool = False,
        orientation_deg: float = 0.0,
    ):
        self.channel = channel
        self.x = float(x)
        self.y = float(y)
        self.R = float(R)
        self.is_directional = is_directional
        self.orientation_deg = float(orientation_deg) % 360.0
        self.cleared = False

    def can_receive(self, px: float, py: float) -> bool:
        """判断位于 (px, py) 的机器狗能否收到该源的信号"""
        if self.cleared:
            return False
        d = math.hypot(px - self.x, py - self.y)
        if d > self.R:
            return False
        if not self.is_directional:
            return True

        # 定向源：只有在发射方向两侧各 90 度（即前向半平面）内才辐射
        # 向量：源 -> 机器狗
        dx = px - self.x
        dy = py - self.y
        if math.hypot(dx, dy) < 1e-6:
            return True
        ang_rad = math.radians(self.orientation_deg)
        ux = math.cos(ang_rad)
        uy = math.sin(ang_rad)
        # 点积 >= 0 说明在定向半平面内
        return (dx * ux + dy * uy) >= -1e-9


class SimEnvironment:
    def __init__(
        self,
        sources: list,
        max_virtual_duration_s: float = 360000.0,
        max_real_duration_s: float = 1200.0,
    ):
        self.sources = {s.channel: s for s in sources}
        self.total_sources = len(sources)
        self.max_virtual_duration_s = max_virtual_duration_s
        self.max_real_duration_s = max_real_duration_s

        # 机器狗初始状态
        self.cur_pos = (0.0, 0.0)
        self.cur_channel = 1
        self.virtual_time_s = 0.0
        self.total_distance_m = 0.0
        self.switch_count = 0
        self.measure_count = 0
        self.clear_fail_count = 0
        self.clear_succ_count = 0

        self.cleared_count = 0
        self.is_entered = False
        self.is_exited = False

    @classmethod
    def generate_random_case(
        cls,
        num_sources: int = 12,
        is_p4: bool = False,
        seed: int = 42,
        dir_ratio: float = 0.5,
    ):
        """生成随机合法测试案例"""
        rng = np.random.default_rng(seed)
        channels = rng.choice(np.arange(1, 21), size=num_sources, replace=False)
        sources = []

        for ch in channels:
            # 均匀分布在 Omega = B((0,0), 1800)
            r = math.sqrt(rng.uniform(0.0, 1.0)) * 1800.0
            theta = rng.uniform(0.0, 2.0 * math.pi)
            x = r * math.cos(theta)
            y = r * math.sin(theta)

            # R in [1000, 1500]
            R = rng.uniform(1000.0, 1500.0)

            if is_p4:
                is_dir = bool(rng.uniform(0.0, 1.0) < dir_ratio)
                ori = rng.uniform(0.0, 360.0) if is_dir else 0.0
            else:
                is_dir = False
                ori = 0.0

            sources.append(
                RadioSource(
                    channel=int(ch),
                    x=x,
                    y=y,
                    R=R,
                    is_directional=is_dir,
                    orientation_deg=ori,
                )
            )

        return cls(sources)

    def _get_noise(self, px: float, py: float, channel: int) -> float:
        """同地点同频道确定性误差生成 [-1.0, 1.0]"""
        # 利用 hash 保证重复检测误差完全相同
        key = f"{round(px, 2)}_{round(py, 2)}_{channel}".encode("utf-8")
        h = int(hashlib.md5(key).hexdigest()[:8], 16)
        # 归一化到 [-1.0, 1.0]
        val = (h / 0xFFFFFFFF) * 2.0 - 1.0
        return val

    def enter(self):
        self.is_entered = True
        return {
            "accepted": True,
            "virtual_time_s": self.virtual_time_s,
            "max_virtual_duration_s": self.max_virtual_duration_s,
            "max_real_duration_s": self.max_real_duration_s,
            "remaining_real_duration_s": int(self.max_real_duration_s),
        }

    def measure(self, target_pos: tuple, channel: int):
        px, py = target_pos
        # 1. 移动耗时
        d_move = math.hypot(px - self.cur_pos[0], py - self.cur_pos[1])
        t_move = d_move / 5.0
        self.total_distance_m += d_move

        # 2. 切换频道耗时 (若变换频道加 1s)
        t_switch = 1.0 if channel != self.cur_channel else 0.0
        if channel != self.cur_channel:
            self.switch_count += 1
            self.cur_channel = channel

        # 3. 检测耗时 5s
        t_action = 5.0
        self.measure_count += 1

        step_time = t_move + t_switch + t_action
        self.virtual_time_s += step_time
        self.cur_pos = (px, py)

        # 4. 判定信号反馈
        src = self.sources.get(channel)
        if src is None or src.cleared or not src.can_receive(px, py):
            return {
                "accepted": True,
                "virtual_time_s": round(self.virtual_time_s, 3),
                "measure_result": "no_signal",
            }

        dist = math.hypot(src.x - px, src.y - py)
        if dist <= 5.0:
            return {
                "accepted": True,
                "virtual_time_s": round(self.virtual_time_s, 3),
                "measure_result": "near",
            }

        # 示向度: 真实方位 (检测点指向干扰源的方位角) + 误差
        true_deg = math.degrees(math.atan2(src.y - py, src.x - px)) % 360.0
        noise = self._get_noise(px, py, channel)
        svd_deg = round((true_deg + noise) % 360.0, 2)

        return {
            "accepted": True,
            "virtual_time_s": round(self.virtual_time_s, 3),
            "measure_result": "direction",
            "svd_deg": svd_deg,
        }

    def clear(self, target_pos: tuple, channel: int):
        px, py = target_pos
        # 1. 移动耗时
        d_move = math.hypot(px - self.cur_pos[0], py - self.cur_pos[1])
        t_move = d_move / 5.0
        self.total_distance_m += d_move
        # clear 不切换测向机频道，t_switch = 0

        self.cur_pos = (px, py)

        src = self.sources.get(channel)
        if src is not None and not src.cleared:
            d = math.hypot(src.x - px, src.y - py)
            if d <= 20.0:
                # 清除成功！耗时 5s
                src.cleared = True
                self.cleared_count += 1
                self.clear_succ_count += 1
                self.virtual_time_s += t_move + 5.0
                return {
                    "accepted": True,
                    "virtual_time_s": round(self.virtual_time_s, 3),
                    "clear_result": "success",
                }

        # 清除失败，耗时 3s
        self.clear_fail_count += 1
        self.virtual_time_s += t_move + 3.0
        return {
            "accepted": True,
            "virtual_time_s": round(self.virtual_time_s, 3),
            "clear_result": "no_target_in_range",
        }

    def exit(self):
        self.is_exited = True
        return {
            "accepted": True,
            "virtual_time_s": round(self.virtual_time_s, 3),
            "exit_reason": "user_exit",
        }


class LocalSimDriver:
    """本地仿真环境驱动器适配接口"""

    def __init__(self, env: SimEnvironment):
        self.env = env

    def enter(self):
        return self.env.enter()

    def measure(self, pos: tuple, channel: int):
        return self.env.measure(pos, channel)

    def clear(self, pos: tuple, channel: int):
        return self.env.clear(pos, channel)

    def exit(self):
        return self.env.exit()
