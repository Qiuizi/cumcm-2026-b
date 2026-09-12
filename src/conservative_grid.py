"""
conservative_grid.py - 在线保守网格管理与单目标有限清除计划
实现方案第 4 节与第 5.1 节：
1. 2米边长网格，外包半径 d_g = sqrt(2) ~ 1.414 米
2. 初始局部坐标 (a, b)，a in [0, 1500], b in [-28, 28]，共 21779 个单元
3. 严格保守删除规则 (留几何裕量 d_g，保证不丢真位置)
4. 安全清除判据：rho(Z) + d_g <= 20 米，或 max ||q - z|| + d_g <= 20 米
5. 225 点基础清除覆盖计划生成与贪心集合覆盖求解
"""

import math
import numpy as np


class ConservativeGrid:
    def __init__(self, p1: tuple, theta1_deg: float, eps_deg: float = 1.005):
        """
        初始化目标频道的首测保守网格
        p1: 首次测得 direction 的位置 (x1, y1)
        theta1_deg: 首次示向度 (度)
        """
        self.p1 = np.array(p1, dtype=float)
        self.theta1_deg = float(theta1_deg)
        self.eps_deg = float(eps_deg)

        # 首测局部坐标系基向量: u 沿示向度, v 沿逆时针垂直
        th_rad = math.radians(self.theta1_deg)
        self.u = np.array([math.cos(th_rad), math.sin(th_rad)], dtype=float)
        self.v = np.array([-math.sin(th_rad), math.cos(th_rad)], dtype=float)

        self.h_g = 2.0
        self.d_g = self.h_g / math.sqrt(2.0)  # ~1.4142m

        # 构造局部网格中心点 (a, b)
        # a: 0, 2, ..., 1500 (751个)
        # b: -28, -26, ..., 28 (29个)
        a_coords = np.arange(0.0, 1500.0 + 1e-3, self.h_g)
        b_coords = np.arange(-28.0, 28.0 + 1e-3, self.h_g)
        A, B = np.meshgrid(a_coords, b_coords)
        self.a_grid = A.flatten()
        self.b_grid = B.flatten()
        self.total_cells = len(self.a_grid)  # 751 * 29 = 21779

        # 全局坐标中心点 (21779, 2)
        self.z_grid = (
            self.p1[None, :]
            + self.a_grid[:, None] * self.u[None, :]
            + self.b_grid[:, None] * self.v[None, :]
        )

        # 存活单元掩码 (True 为存活)
        self.alive = np.ones(self.total_cells, dtype=bool)

        # 初始首测楔形几何过滤
        self._initial_prune()

    def clone(self):
        """深拷贝当前保守网格副本，用于闭环预测模拟"""
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
        return new_grid

    def _initial_prune(self):
        """初始首测物理条件过滤：目标在 Omega (1800m) 内，首测距离在 (5, 1500]"""
        z = self.z_grid
        # 1. 目标在 Omega 内: ||z|| - d_g <= 1800
        dist_orig = np.linalg.norm(z, axis=1)
        self.alive &= (dist_orig - self.d_g <= 1800.0)

        # 2. 首测点阳性接收距离 <= 1500: ||z - p1|| - d_g <= 1500
        dist_p1 = np.linalg.norm(z - self.p1, axis=1)
        self.alive &= (dist_p1 - self.d_g <= 1500.0)

        # 3. 首测非 near: ||z - p1|| + d_g > 5
        self.alive &= (dist_p1 + self.d_g > 5.0)

        # 4. 首测角域: |b| <= a * tan(eps) + d_g / cos(eps)
        eps_rad = math.radians(self.eps_deg)
        sin_eps = math.sin(eps_rad)
        cos_eps = math.cos(eps_rad)
        # 法向量 n1 = (-sin_eps, cos_eps), n2 = (-sin_eps, -cos_eps)
        # 在局部坐标系下：a*sin_eps - |b|*cos_eps >= -d_g
        self.alive &= (self.a_grid * sin_eps - np.abs(self.b_grid) * cos_eps >= -self.d_g)

    def prune_by_direction(self, p: tuple, theta_deg: float, eps_deg: float = 1.005):
        """根据新的 direction 观测保守删除单元"""
        if not np.any(self.alive):
            return
        p_arr = np.array(p, dtype=float)
        th_rad = math.radians(theta_deg)
        eps_rad = math.radians(eps_deg)

        # 存活点
        indices = np.where(self.alive)[0]
        z_sub = self.z_grid[indices]
        rel = z_sub - p_arr[None, :]

        # 1. 阳性接收距离 <= 1500
        dists = np.linalg.norm(rel, axis=1)
        mask_dist = (dists - self.d_g <= 1500.0) & (dists + self.d_g > 5.0)

        # 2. 角域半平面检验
        # 射线顺时针与逆时针界
        th_min = th_rad - eps_rad
        th_max = th_rad + eps_rad
        # 顺时针法向量: (sin(th_min), -cos(th_min))
        # 逆时针法向量: (-sin(th_max), cos(th_max))
        # 前向法向量: (-cos(th), -sin(th))
        n1 = np.array([math.sin(th_min), -math.cos(th_min)])
        n2 = np.array([-math.sin(th_max), math.cos(th_max)])
        nf = np.array([-math.cos(th_rad), -math.sin(th_rad)])

        dot1 = rel @ n1
        dot2 = rel @ n2
        dotf = rel @ nf

        # 保守保留条件: dot <= d_g * ||n|| = d_g
        mask_angle = (dot1 <= self.d_g) & (dot2 <= self.d_g) & (dotf <= self.d_g)

        self.alive[indices[~(mask_dist & mask_angle)]] = False

    def prune_by_near(self, p: tuple):
        """根据 near 反馈保守删除：距离大于 5 米的删除"""
        if not np.any(self.alive):
            return
        p_arr = np.array(p, dtype=float)
        indices = np.where(self.alive)[0]
        dists = np.linalg.norm(self.z_grid[indices] - p_arr[None, :], axis=1)
        # 若 ||z - p|| - d_g > 5 则删除
        self.alive[indices[dists - self.d_g > 5.0]] = False

    def prune_by_no_signal_omni(self, q: tuple):
        """P3 全向源 no_signal: ||z - q|| + d_g <= 1000 则删除"""
        if not np.any(self.alive):
            return
        q_arr = np.array(q, dtype=float)
        indices = np.where(self.alive)[0]
        dists = np.linalg.norm(self.z_grid[indices] - q_arr[None, :], axis=1)
        self.alive[indices[dists + self.d_g <= 1000.0]] = False

    def prune_by_clear_fail(self, q: tuple):
        """清除失败反馈: ||z - q|| + d_g <= 20 则删除"""
        if not np.any(self.alive):
            return
        q_arr = np.array(q, dtype=float)
        indices = np.where(self.alive)[0]
        dists = np.linalg.norm(self.z_grid[indices] - q_arr[None, :], axis=1)
        self.alive[indices[dists + self.d_g <= 20.0]] = False

    def get_surviving_cells(self):
        """获取所有保留存活单元的全局中心坐标"""
        return self.z_grid[self.alive]

    def count(self) -> int:
        return int(np.sum(self.alive))

    def get_bounding_features(self):
        """计算保留单元的均值中心 mu、长轴单位向量 u_major、长轴跨度 L"""
        cells = self.get_surviving_cells()
        if len(cells) == 0:
            return self.p1, self.u, 0.0
        mu = np.mean(cells, axis=0)
        if len(cells) == 1:
            return mu, self.u, 0.0

        # PCA 计算主轴
        rel = cells - mu[None, :]
        cov = rel.T @ rel
        eigvals, eigvecs = np.linalg.eigh(cov)
        u_major = eigvecs[:, 1]  # 最大特征值对应的特征向量

        projs = rel @ u_major
        L = float(np.max(projs) - np.min(projs))
        return mu, u_major, L

    def check_safe_clear_at(self, q: tuple) -> bool:
        """检查点 q 是否能保证安全清除所有保留单元 (max ||q - z|| + d_g <= 20)"""
        cells = self.get_surviving_cells()
        if len(cells) == 0:
            return True
        q_arr = np.array(q, dtype=float)
        dists = np.linalg.norm(cells - q_arr[None, :], axis=1)
        return bool(np.max(dists) + self.d_g <= 20.0)

    def find_safe_clear_position(self, cur_p: tuple):
        """
        寻找单个安全清除位置：
        若当前点满足条件返回 cur_p；
        若最小包围球半径 rho + d_g <= 20，返回球心或线段最近点；
        否则返回 None。
        """
        if self.check_safe_clear_at(cur_p):
            return cur_p

        cells = self.get_surviving_cells()
        if len(cells) == 0:
            return cur_p

        # 凸包/极值点近似最小覆盖圆
        # 取均值中心作为候选球心
        mu = np.mean(cells, axis=0)
        dists = np.linalg.norm(cells - mu[None, :], axis=1)
        max_d = float(np.max(dists))
        if max_d + self.d_g <= 20.0:
            return (float(mu[0]), float(mu[1]))

        # 二分优化查找更优球心 (简单的梯度步进)
        center = mu.copy()
        for _ in range(10):
            dists = np.linalg.norm(cells - center[None, :], axis=1)
            idx_max = np.argmax(dists)
            if dists[idx_max] + self.d_g <= 20.0:
                return (float(center[0]), float(center[1]))
            # 沿最远点方向微调
            center += 0.2 * (cells[idx_max] - center)

        dists = np.linalg.norm(cells - center[None, :], axis=1)
        if np.max(dists) + self.d_g <= 20.0:
            return (float(center[0]), float(center[1]))
        return None

    def build_clear_plan(self, cur_p: tuple, anchor_a: tuple = None):
        """
        方案第 5.1 节：始终准备一条有限清除计划
        使用 225 个预设中心进行贪心集合覆盖
        返回清除动作序列 [(x, y), ...]
        """
        # 1. 检查是否存在单点安全清除位置
        safe_pos = self.find_safe_clear_position(cur_p)
        if safe_pos is not None:
            return [safe_pos]

        cells = self.get_surviving_cells()
        if len(cells) == 0:
            return [cur_p]

        # 2. 预设 225 个清除候选中心
        # g_{i, k} = p1 + (10 + 20*i)*u + 20*k*v, i=0..74, k=-1,0,1
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

        r_cov = 20.0 - self.d_g  # ~18.5858m

        # 若存活单元较多，为了极致速度可每隔 2~4 个抽样代表点
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

        # 一次性计算覆盖布尔矩阵 (N_centers, N_sample)
        dists_mat = np.linalg.norm(valid_centers[:, None, :] - sample_cells[None, :, :], axis=2)
        cov_matrix = (dists_mat <= r_cov)

        covered = np.zeros(n_sample, dtype=bool)
        selected_centers = []

        for _ in range(min(50, len(valid_centers))):
            if np.all(covered):
                break
            # 统计各中心对当前未覆盖样本的覆盖数
            uncovered_mask = ~covered
            counts = np.sum(cov_matrix[:, uncovered_mask], axis=1)
            best_idx = np.argmax(counts)
            if counts[best_idx] == 0:
                # 补充未覆盖样本的均值中心
                supp_c = np.mean(sample_cells[uncovered_mask], axis=0)
                selected_centers.append((float(supp_c[0]), float(supp_c[1])))
                break
            best_c = valid_centers[best_idx]
            selected_centers.append((float(best_c[0]), float(best_c[1])))
            covered |= cov_matrix[best_idx]

        if not selected_centers:
            mu = np.mean(cells, axis=0)
            selected_centers = [(float(mu[0]), float(mu[1]))]

        # 3. 对所选中心进行最近邻访问排序
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

        # 4. 保证计划对全部保留单元安全覆盖：以现有 tour 为前缀，为未覆盖部分继续追加清除点
        plan_arr = np.array(tour)
        dists = np.min(np.linalg.norm(cells[:, None, :] - plan_arr[None, :, :], axis=2), axis=1)
        uncovered = cells[dists > r_cov].copy()

        while len(uncovered) > 0:
            if len(uncovered) > 300:
                sub_cand = uncovered[::max(1, len(uncovered) // 200)]
            else:
                sub_cand = uncovered

            d_mat = np.linalg.norm(sub_cand[:, None, :] - uncovered[None, :, :], axis=2)
            cov_mat = (d_mat <= r_cov)
            counts = np.sum(cov_mat, axis=1)
            best_i = np.argmax(counts)
            best_pt = sub_cand[best_i]

            tour.append((float(best_pt[0]), float(best_pt[1])))
            rem_mask = np.linalg.norm(uncovered - best_pt[None, :], axis=1) > r_cov
            uncovered = uncovered[rem_mask]

        return tour
