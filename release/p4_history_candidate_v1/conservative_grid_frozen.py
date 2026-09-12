"""
conservative_grid_frozen.py - P4 严格冻结专用保守网格管理与清除计划
完全保留原始冻结版逻辑，与 P3 共享模块后续修改彻底隔离。
"""

import math
import numpy as np


class ConservativeGrid:
    def __init__(self, p1: tuple, theta1_deg: float, eps_deg: float = 1.005):
        self.p1 = np.array(p1, dtype=float)
        self.theta1_deg = float(theta1_deg)
        self.eps_deg = float(eps_deg)

        th_rad = math.radians(self.theta1_deg)
        self.u = np.array([math.cos(th_rad), math.sin(th_rad)], dtype=float)
        self.v = np.array([-math.sin(th_rad), math.cos(th_rad)], dtype=float)

        self.h_g = 2.0
        self.d_g = self.h_g / math.sqrt(2.0)  # ~1.4142m

        a_coords = np.arange(0.0, 1500.0 + 1e-3, self.h_g)
        b_coords = np.arange(-28.0, 28.0 + 1e-3, self.h_g)
        A, B = np.meshgrid(a_coords, b_coords)
        self.a_grid = A.flatten()
        self.b_grid = B.flatten()
        self.total_cells = len(self.a_grid)

        self.z_grid = (
            self.p1[None, :]
            + self.a_grid[:, None] * self.u[None, :]
            + self.b_grid[:, None] * self.v[None, :]
        )
        self.alive = np.ones(self.total_cells, dtype=bool)
        # 模型矛盾与裁剪拒绝记录：
        # 空存活集不构成任何"目标不存在/已清除"或"可安全清除"的依据，必须显式留痕。
        self.contradiction = False
        self.contradiction_events = []
        self.rejected_prune_count = 0
        self._initial_prune()

    def clone(self):
        new_grid = ConservativeGrid.__new__(ConservativeGrid)
        new_grid.p1 = self.p1.copy()
        new_grid.theta1_deg = self.theta1_deg
        new_grid.eps_deg = self.eps_deg
        new_grid.u = self.u.copy()
        new_grid.v = self.v.copy()
        new_grid.h_g = self.h_g
        new_grid.d_g = self.d_g
        new_grid.a_grid = self.a_grid
        new_grid.b_grid = self.b_grid
        new_grid.total_cells = self.total_cells
        new_grid.z_grid = self.z_grid
        new_grid.alive = np.copy(self.alive)
        new_grid.contradiction = self.contradiction
        new_grid.contradiction_events = list(self.contradiction_events)
        new_grid.rejected_prune_count = self.rejected_prune_count
        return new_grid

    def _apply_observation_prune(self, mask, kind: str, detail: dict) -> bool:
        """统一的观测裁剪入口（保守语义，修正"整集被清空"的错误状态变化）。

        规则：
        - 合法观测只允许在存活集内部收缩，绝不把存活集裁成空集；
        - 若某次观测会导致存活集被完全清空，说明模型与观测矛盾，
          此时**不应用**该次裁剪（保留上一版有效状态）并留痕；
        - 矛盾绝不被解释为"目标不存在"或"目标已清除"。
        """
        new_alive = self.alive & mask
        if not np.any(new_alive):
            self.rejected_prune_count += 1
            self.contradiction_events.append({
                "kind": kind,
                "detail": detail,
                "alive_before": int(np.sum(self.alive)),
                "action": "prune_rejected_keep_last_consistent_state",
            })
            if kind == "direction":
                # 测向观测与全部存活单元矛盾：标记模型矛盾，交由上层显式判失败
                self.contradiction = True
            return False
        self.alive = new_alive
        return True

    def _initial_prune(self):
        z = self.z_grid
        dist_orig = np.linalg.norm(z, axis=1)
        self.alive &= (dist_orig - self.d_g <= 1800.0)
        dist_p1 = np.linalg.norm(z - self.p1, axis=1)
        self.alive &= (dist_p1 - self.d_g <= 1500.0)
        self.alive &= (dist_p1 + self.d_g > 5.0)

        eps_rad = math.radians(self.eps_deg)
        sin_eps = math.sin(eps_rad)
        cos_eps = math.cos(eps_rad)
        self.alive &= (self.a_grid * sin_eps - np.abs(self.b_grid) * cos_eps >= -self.d_g)

    def prune_by_direction(self, p: tuple, theta_deg: float, eps_deg: float = 1.005):
        if not np.any(self.alive):
            return
        p_arr = np.array(p, dtype=float)
        rel = self.z_grid - p_arr[None, :]
        dists = np.linalg.norm(rel, axis=1)

        th_rad = math.radians(theta_deg)
        e_rad = math.radians(eps_deg)
        th_min = th_rad - e_rad
        th_max = th_rad + e_rad

        # 【修复】角域楔形检验的外法向与比较方向：
        # 旧实现在此处把两个法向写反并用 <= 比较，等价于检验"楔形之外"，
        # 导致任意一次合法测向观测都把存活集清空（包含真实位置所在单元）。
        # 现与共享实现 src/conservative_grid.py 及本模块内的预测模型保持一致：
        #   n1 = ( sin(th_min), -cos(th_min))
        #   n2 = (-sin(th_max),  cos(th_max))
        #   nf = (-cos(th_rad), -sin(th_rad))
        # 并统一使用 dot(...) <= d_g 作为"位于楔形内"的保守判据。
        n1 = np.array([math.sin(th_min), -math.cos(th_min)])
        n2 = np.array([-math.sin(th_max), math.cos(th_max)])
        nf = np.array([-math.cos(th_rad), -math.sin(th_rad)])

        in_cone = (
            (np.dot(rel, n1) <= self.d_g)
            & (np.dot(rel, n2) <= self.d_g)
            & (np.dot(rel, nf) <= self.d_g)
        )
        in_range = (dists - self.d_g <= 1500.0)
        not_near = (dists + self.d_g > 5.0)

        self._apply_observation_prune(
            in_cone & in_range & not_near,
            "direction",
            {"p": [round(float(p_arr[0]), 3), round(float(p_arr[1]), 3)],
             "theta_deg": round(float(theta_deg), 4), "eps_deg": round(float(eps_deg), 4)},
        )

    def prune_by_no_signal_omni(self, p: tuple):
        if not np.any(self.alive):
            return
        p_arr = np.array(p, dtype=float)
        dists = np.linalg.norm(self.z_grid - p_arr[None, :], axis=1)
        self._apply_observation_prune(dists + self.d_g > 1000.0, "no_signal",
                                      {"p": [round(float(p_arr[0]), 3), round(float(p_arr[1]), 3)]})

    def prune_by_near(self, p: tuple):
        """【修复·缺陷4】合法 near 反馈：测站 5m 内存在目标。

        语义（与共享实现 src/conservative_grid.py 一致，且**不是** no_signal 的全向距离排除）：
        保留 ||z - p|| - d_g <= 5.0 的单元，其余删除。
        """
        if not np.any(self.alive):
            return
        p_arr = np.array(p, dtype=float)
        dists = np.linalg.norm(self.z_grid - p_arr[None, :], axis=1)
        self._apply_observation_prune(dists - self.d_g <= 5.0, "near",
                                      {"p": [round(float(p_arr[0]), 3), round(float(p_arr[1]), 3)]})

    def prune_by_clear_fail(self, q: tuple):
        if not np.any(self.alive):
            return
        q_arr = np.array(q, dtype=float)
        dists = np.linalg.norm(self.z_grid - q_arr[None, :], axis=1)
        # 清除失败只是"20m 内无目标"，同样不允许把存活集裁空（裁空即模型矛盾）
        self._apply_observation_prune(dists + self.d_g > 20.0, "clear_fail",
                                      {"q": [round(float(q_arr[0]), 3), round(float(q_arr[1]), 3)]})

    def count(self) -> int:
        return int(np.sum(self.alive))

    def get_surviving_cells(self) -> np.ndarray:
        return self.z_grid[self.alive]

    def get_bounding_features(self):
        cells = self.get_surviving_cells()
        if len(cells) == 0:
            return self.p1.copy(), self.u.copy(), 0.0
        mu = np.mean(cells, axis=0)
        diff = cells - mu[None, :]
        dists = np.linalg.norm(diff, axis=1)
        L = float(np.max(dists)) if len(dists) > 0 else 0.0
        u_major = diff[np.argmax(dists)] / (L + 1e-9) if L > 1e-3 else self.u.copy()
        return mu, u_major, L

    def check_safe_clear_at(self, q: tuple) -> bool:
        cells = self.get_surviving_cells()
        if len(cells) == 0:
            # 【修复】空集不构成任何安全清除依据。
            # 旧实现返回 True，使 find_safe_clear_position 直接返回当前点，
            # 决策器给出 reason='safe_clear_guaranteed' 的固定点清除并无限重试。
            return False
        q_arr = np.array(q, dtype=float)
        dists = np.linalg.norm(cells - q_arr[None, :], axis=1)
        return bool(np.max(dists) + self.d_g <= 20.0)

    def find_safe_clear_position(self, cur_p: tuple):
        if self.check_safe_clear_at(cur_p):
            return cur_p

        cells = self.get_surviving_cells()
        if len(cells) == 0:
            # 【修复】无有效状态可用，返回 None 交由上层显式判失败，不伪造"可安全清除"
            return None

        mu = np.mean(cells, axis=0)
        dists = np.linalg.norm(cells - mu[None, :], axis=1)
        max_d = float(np.max(dists))
        if max_d + self.d_g <= 20.0:
            return (float(mu[0]), float(mu[1]))

        center = mu.copy()
        for _ in range(10):
            dists = np.linalg.norm(cells - center[None, :], axis=1)
            idx_max = np.argmax(dists)
            if dists[idx_max] + self.d_g <= 20.0:
                return (float(center[0]), float(center[1]))
            center += 0.2 * (cells[idx_max] - center)

        dists = np.linalg.norm(cells - center[None, :], axis=1)
        if np.max(dists) + self.d_g <= 20.0:
            return (float(center[0]), float(center[1]))
        return None

    def build_clear_plan(self, cur_p: tuple, anchor_a: tuple = None):
        """原始冻结版清除计划：50 步截断贪心覆盖"""
        safe_pos = self.find_safe_clear_position(cur_p)
        if safe_pos is not None:
            return [safe_pos]

        cells = self.get_surviving_cells()
        if len(cells) == 0:
            # 【修复】空集下不存在合法清除计划，返回空计划（不是"原地清除"）
            return []

        i_idx = np.arange(75)
        k_idx = np.array([-1.0, 0.0, 1.0])
        I, K = np.meshgrid(i_idx, k_idx)
        centers_a = 10.0 + 20.0 * I.flatten()
        centers_b = 20.0 * K.flatten()

        centers_global = (
            self.p1[None, :]
            + centers_a[:, None] * self.u[None, :]
            + centers_b[:, None] * self.v[None, :]
        )

        r_cov = 20.0 - self.d_g

        if len(cells) > 500:
            stride = max(1, len(cells) // 400)
            sample_cells = cells[::stride]
        else:
            sample_cells = cells

        n_sample = len(sample_cells)
        min_c = np.min(sample_cells, axis=0) - 25.0
        max_c = np.max(sample_cells, axis=0) + 25.0
        valid_mask = np.all((centers_global >= min_c) & (centers_global <= max_c), axis=1)
        valid_centers = centers_global[valid_mask]
        if len(valid_centers) == 0:
            valid_centers = centers_global

        dists_mat = np.linalg.norm(valid_centers[:, None, :] - sample_cells[None, :, :], axis=2)
        cov_matrix = (dists_mat <= r_cov)

        covered = np.zeros(n_sample, dtype=bool)
        selected_centers = []

        # 【修复·缺陷3】取消 50 步人为截断：迭代上界改为候选中心总数，
        # 真正结束条件只有"样本已全覆盖"或"无中心还能覆盖未覆盖样本"。
        for _ in range(len(valid_centers)):
            if np.all(covered):
                break
            uncovered_mask = ~covered
            counts = np.sum(cov_matrix[:, uncovered_mask], axis=1)
            best_idx = np.argmax(counts)
            if counts[best_idx] == 0:
                supp_c = np.mean(sample_cells[uncovered_mask], axis=0)
                selected_centers.append((float(supp_c[0]), float(supp_c[1])))
                break
            best_c = valid_centers[best_idx]
            selected_centers.append((float(best_c[0]), float(best_c[1])))
            covered |= cov_matrix[best_idx]

        if not selected_centers:
            mu = np.mean(cells, axis=0)
            selected_centers = [(float(mu[0]), float(mu[1]))]

        if len(selected_centers) <= 1:
            return selected_centers

        cur = np.array(cur_p, dtype=float)
        remaining = list(range(len(selected_centers)))
        tour = []
        last_pos = cur

        while remaining:
            best_r = -1
            best_d = 1e9
            for r in remaining:
                c = np.array(selected_centers[r])
                d = np.linalg.norm(c - last_pos)
                if d < best_d:
                    best_d = d
                    best_r = r
            tour.append(selected_centers[best_r])
            last_pos = np.array(selected_centers[best_r])
            remaining.remove(best_r)

        # 【修复·缺陷3】对**全部存活单元**（不是抽样样本）补齐覆盖：
        # 逐个检查每个存活单元中心 z，若不存在计划点 q 使 ||z-q|| + d_g <= 20，
        # 就继续追加清除点，直到每个单元都被某个计划点覆盖。
        # 预测与执行都走这一个生成器，因此"计划可覆盖"与"实际可清除"一致。
        if len(tour) == 0:
            return []

        plan_arr = np.array(tour, dtype=float)
        dists_to_plan = np.min(
            np.linalg.norm(cells[:, None, :] - plan_arr[None, :, :], axis=2), axis=1
        )
        uncovered = cells[dists_to_plan > r_cov].copy()

        while len(uncovered) > 0:
            if len(uncovered) > 300:
                sub_cand = uncovered[:: max(1, len(uncovered) // 200)]
            else:
                sub_cand = uncovered

            d_mat = np.linalg.norm(sub_cand[:, None, :] - uncovered[None, :, :], axis=2)
            cov_mat = (d_mat <= r_cov)
            counts = np.sum(cov_mat, axis=1)
            best_pt = sub_cand[int(np.argmax(counts))]

            tour.append((float(best_pt[0]), float(best_pt[1])))
            still = np.linalg.norm(uncovered - best_pt[None, :], axis=1) > r_cov
            uncovered = uncovered[still]

        return tour

    def verify_full_coverage(self, plan) -> tuple:
        """验收用：检查计划是否覆盖**全部**存活单元。
        返回 (是否全覆盖, 未覆盖单元数, 最大未覆盖间隙 ||z-q||_min)。"""
        cells = self.get_surviving_cells()
        if len(cells) == 0:
            return True, 0, 0.0
        if plan is None or len(plan) == 0:
            return False, len(cells), None
        plan_arr = np.array(plan, dtype=float)
        dmin = np.min(np.linalg.norm(cells[:, None, :] - plan_arr[None, :, :], axis=2), axis=1)
        gap = dmin - (20.0 - self.d_g)
        uncovered = int(np.sum(gap > 1e-9))
        return bool(uncovered == 0), uncovered, float(np.max(gap))
