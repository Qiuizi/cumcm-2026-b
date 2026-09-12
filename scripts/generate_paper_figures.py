"""
generate_paper_figures.py - 生成数学建模论文所需的全部高精度矢量/位图图件
包含：
1. fig1_p1_geometry: 问题一示向角域与三站反例几何构型图
2. fig2_p2_candidate: 问题二Gamma_0充分候选区与J2代价热力图/近优区R30
3. fig3_p3_topology: 问题三7点保障覆盖布局与168连续区域单元示意图
4. fig4_p4_topology: 问题四25点32三角形覆盖网格与凸包包含特性图
5. fig5_benchmark: 问题三与问题四版本B与版本C实测性能对比图
6. fig6_tech_roadmap: 全局协同搜索-定位-清除证据链技术路线图
"""

import os
import sys
import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.path import Path

# 配置中文字体与负号显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 300

os.makedirs("figures", exist_ok=True)

# ==============================================================================
# 1. 图1：问题一 示向角域与三站反例几何构型
# ==============================================================================
def generate_fig1():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6))

    # 子图 (a): 典型两站角域交会多边形
    ax1.set_title("(a) 两站角域半平面交会与多边形包络", fontsize=12, fontweight='bold', pad=10)
    p1 = np.array([0, 0])
    p2 = np.array([600, -200])
    target = np.array([400, 500])
    
    ax1.plot(p1[0], p1[1], 'bs', markersize=8, label='检测站 $p_1$ (0, 0)')
    ax1.plot(p2[0], p2[1], 'g^', markersize=8, label='检测站 $p_2$ (600, -200)')
    ax1.plot(target[0], target[1], 'r*', markersize=12, label='真实目标 (400, 500)')

    # 绘制射线与角域扇形（示向角误差 +/- 1 度）
    theta1 = math.degrees(math.atan2(target[1] - p1[1], target[0] - p1[0]))
    theta2 = math.degrees(math.atan2(target[1] - p2[1], target[0] - p2[0]))

    wedge1 = patches.Wedge(p1, 900, theta1 - 1.0, theta1 + 1.0, color='blue', alpha=0.2, label='测向角域 $W_1$ (±1°)')
    wedge2 = patches.Wedge(p2, 900, theta2 - 1.0, theta2 + 1.0, color='green', alpha=0.2, label='测向角域 $W_2$ (±1°)')
    ax1.add_patch(wedge1)
    ax1.add_patch(wedge2)

    # 示意交会区域放大
    poly_pts = np.array([[385, 485], [415, 492], [418, 515], [388, 508]])
    poly_patch = patches.Polygon(poly_pts, closed=True, edgecolor='crimson', facecolor='yellow', alpha=0.6, linewidth=2, label='交会多边形 $C$')
    ax1.add_patch(poly_patch)

    ax1.set_xlim(-100, 800)
    ax1.set_ylim(-300, 750)
    ax1.set_xlabel("X 坐标 (米)", fontsize=10)
    ax1.set_ylabel("Y 坐标 (米)", fontsize=10)
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.legend(loc='lower left', fontsize=9)
    ax1.set_aspect('equal')

    # 子图 (b): 严格三站反例几何构型
    ax2.set_title("(b) 三站反例：$D=40$m 但 $\\rho=23.094$m > 20m", fontsize=12, fontweight='bold', pad=10)
    h = 20.0 / math.sqrt(3.0)
    A = np.array([h, 20.0])
    B = np.array([h, -20.0])
    C = np.array([-2.0 * h, 0.0])
    
    tri = patches.Polygon([A, B, C], closed=True, edgecolor='darkred', facecolor='lightsalmon', alpha=0.5, linewidth=2.5, label='可行区域 (正三角形，边长40m)')
    ax2.add_patch(tri)

    # 最远点对与直径圆 (以 AB 为直径的圆)
    diam_center = (A + B) / 2.0
    diam_circle = patches.Circle(diam_center, 20.0, edgecolor='blue', facecolor='none', linestyle='--', linewidth=2, label='以最远点对 $AB$ 为直径的圆 ($r=20$m)')
    ax2.add_patch(diam_circle)

    # 最小覆盖圆 (MEC，圆心在原点，半径 40/sqrt(3) ≈ 23.094m)
    mec_circle = patches.Circle([0, 0], 40.0 / math.sqrt(3.0), edgecolor='purple', facecolor='none', linestyle='-', linewidth=2.2, label='最小覆盖圆 ($\\rho=23.094$m)')
    ax2.add_patch(mec_circle)

    # 标记顶点
    ax2.plot(A[0], A[1], 'ro', markersize=7)
    ax2.text(A[0]+1, A[1]+1, '$A(11.55, 20.0)$', fontsize=9, fontweight='bold')
    ax2.plot(B[0], B[1], 'ro', markersize=7)
    ax2.text(B[0]+1, B[1]-3, '$B(11.55, -20.0)$', fontsize=9, fontweight='bold')
    ax2.plot(C[0], C[1], 'ko', markersize=7)
    ax2.text(C[0]-14, C[1], '$C(-23.09, 0)$', fontsize=9, fontweight='bold', color='darkblue')

    ax2.plot(0, 0, 'kx', markersize=8, label='最小覆盖圆心 (0, 0)')
    ax2.plot(diam_center[0], diam_center[1], 'b+', markersize=8, label='直径中点 (11.55, 0)')

    # 标注第三顶点在直径圆外
    ax2.annotate('第三顶点 $C$ 在直径圆外！\n$(A-C)\\cdot(B-C) = 800 > 0$', 
                 xy=(C[0], C[1]), xytext=(-35, -18),
                 arrowprops=dict(facecolor='black', shrink=0.08, width=1.5, headwidth=6),
                 fontsize=9, bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.8))

    ax2.set_xlim(-40, 40)
    ax2.set_ylim(-35, 35)
    ax2.set_xlabel("局部 X 坐标 (米)", fontsize=10)
    ax2.set_ylabel("局部 Y 坐标 (米)", fontsize=10)
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.legend(loc='upper left', fontsize=8.5)
    ax2.set_aspect('equal')

    plt.tight_layout()
    fig_path = os.path.join("figures", "fig1_p1_geometry.png")
    plt.savefig(fig_path)
    plt.close()
    print(f"Generated: {fig_path}")

# ==============================================================================
# 2. 图2：问题二 Gamma_0 充分候选区与 J2 代价热力分布
# ==============================================================================
def generate_fig2():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # 子图 (a): Gamma_0 三圆交集推导几何示意图
    ax1.set_title("(a) 第二检测点充分接收候选域 $\\Gamma_0$ 几何构造", fontsize=12, fontweight='bold', pad=10)
    eps = math.radians(1.005)
    c_plus = 1000.0 * np.array([math.cos(eps), math.sin(eps)])
    c_minus = 1000.0 * np.array([math.cos(eps), -math.sin(eps)])

    circle_p1 = patches.Circle([0, 0], 1000, edgecolor='gray', facecolor='none', linestyle=':', label='基准圆 $B(p_1, 1000)$')
    circle_cp = patches.Circle(c_plus, 1000, edgecolor='blue', facecolor='none', linestyle='--', label='极限圆 $B(c_+, 1000)$')
    circle_cm = patches.Circle(c_minus, 1000, edgecolor='green', facecolor='none', linestyle='--', label='极限圆 $B(c_-, 1000)$')
    ax1.add_patch(circle_p1)
    ax1.add_patch(circle_cp)
    ax1.add_patch(circle_cm)

    # 绘制实际 Gamma_0 形状
    a_grid = np.linspace(0, 1000, 200)
    b_grid = np.linspace(-600, 600, 240)
    A, B = np.meshgrid(a_grid, b_grid)
    mask = (A >= 0) & (A**2 + B**2 <= 1000**2) & (A**2 + B**2 <= 2000.0 * (A * math.cos(eps) - np.abs(B) * math.sin(eps)))
    ax1.contourf(A, B, mask.astype(int), levels=[0.5, 1.5], colors=['dodgerblue'], alpha=0.35)
    ax1.contour(A, B, mask.astype(int), levels=[0.5], colors=['darkblue'], linewidths=2)

    ax1.plot(0, 0, 'bs', markersize=8, label='首测点 $p_1$ (0,0)')
    ax1.plot([0, 1100], [0, 0], 'r--', linewidth=1.5, label='首测示向轴 $u$')
    ax1.text(600, 20, '示向方向 $u$', color='red', fontsize=10, fontweight='bold')
    ax1.text(350, 250, '候选区域 $\\Gamma_0$', color='darkblue', fontsize=11, fontweight='bold')

    ax1.set_xlim(-100, 1100)
    ax1.set_ylim(-550, 550)
    ax1.set_xlabel("示向轴 $a$ (米)", fontsize=10)
    ax1.set_ylabel("侧移轴 $b$ (米)", fontsize=10)
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.legend(loc='lower left', fontsize=8.5)
    ax1.set_aspect('equal')

    # 子图 (b): J2(q) 目标函数热力分布与 R30 近优区域
    ax2.set_title("(b) 综合代价 $J_2(q)$ 等高线与近优区域 $R_{30}$ 分布", fontsize=12, fontweight='bold', pad=10)
    
    # 读取或模拟 J2 数据
    csv_path = os.path.join("results", "p2_optimization_results.csv")
    if os.path.exists(csv_path):
        import csv
        pts_a, pts_b, pts_j2, pts_r30 = [], [], [], []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pts_a.append(float(row['a']))
                pts_b.append(float(row['b']))
                pts_j2.append(float(row['J2']))
                pts_r30.append(int(row['in_R30']))
        
        sc = ax2.scatter(pts_a, pts_b, c=pts_j2, cmap='viridis_r', s=12, alpha=0.7, label='候选点 $J_2(q)$')
        cbar = plt.colorbar(sc, ax=ax2)
        cbar.set_label('综合期望耗时 $J_2$ (秒)', fontsize=10)

        # 突出显示 R30 近优区域边界和点
        r30_a = [pts_a[i] for i in range(len(pts_a)) if pts_r30[i] == 1]
        r30_b = [pts_b[i] for i in range(len(pts_b)) if pts_r30[i] == 1]
        ax2.scatter(r30_a, r30_b, color='coral', s=15, alpha=0.5, label='近优区域 $R_{30}$ ($\\Delta J_2 \\leq q 30$s)')

        # 最优选定点 (550.0, 164.84)
        min_idx = np.argmin(pts_j2)
        best_a, best_b, min_j2 = pts_a[min_idx], pts_b[min_idx], pts_j2[min_idx]
        ax2.plot(best_a, best_b, 'r*', markersize=14, markeredgecolor='black', label=f'最优第二点 $q^*$ ({best_a:.0f}, {best_b:.1f})\n$J_2^* = {min_j2:.2f}$ 秒')
    
    ax2.set_xlim(0, 1050)
    ax2.set_ylim(-550, 550)
    ax2.set_xlabel("示向轴 $a$ (米)", fontsize=10)
    ax2.set_ylabel("侧移轴 $b$ (米)", fontsize=10)
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.legend(loc='lower left', fontsize=8.5)
    ax2.set_aspect('equal')

    plt.tight_layout()
    fig_path = os.path.join("figures", "fig2_p2_candidate.png")
    plt.savefig(fig_path)
    plt.close()
    print(f"Generated: {fig_path}")

# ==============================================================================
# 3. 图3：问题三 7点保障覆盖布局与168连续区域单元
# ==============================================================================
def generate_fig3():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6))

    # 子图 (a): 7点圆盘覆盖
    ax1.set_title("(a) 问题三 7 点固定保障圆盘覆盖 $\\Omega = B(0, 1800)$", fontsize=12, fontweight='bold', pad=10)
    omega = patches.Circle([0, 0], 1800, edgecolor='red', facecolor='none', linewidth=2, linestyle='-', label='搜索圆域 $\\Omega$ ($R=1800$m)')
    ax1.add_patch(omega)

    q_pts = []
    for i in range(7):
        angle = 2.0 * math.pi * i / 7.0
        qx = 999.0 * math.cos(angle)
        qy = 999.0 * math.sin(angle)
        q_pts.append((qx, qy))
        c_disc = patches.Circle([qx, qy], 1000, edgecolor='steelblue', facecolor='lightblue', alpha=0.2, linewidth=1.5)
        ax1.add_patch(c_disc)
        ax1.plot(qx, qy, 'ro', markersize=7)
        ax1.text(qx + 40, qy + 40, f'$q_{i}$', fontsize=10, fontweight='bold', color='darkblue')

    # 绘制固定巡回路线 (原点出发并依次访问)
    route_x = [0] + [pt[0] for pt in q_pts]
    route_y = [0] + [pt[1] for pt in q_pts]
    ax1.plot(route_x, route_y, 'k--', linewidth=1.8, label='开放巡回基线 ($L_7 \\approx 6200.4$m)')
    ax1.plot(0, 0, 'gs', markersize=9, label='出发原点 $O(0,0)$')

    ax1.set_xlim(-2100, 2100)
    ax1.set_ylim(-2100, 2100)
    ax1.set_xlabel("X 坐标 (米)", fontsize=10)
    ax1.set_ylabel("Y 坐标 (米)", fontsize=10)
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.legend(loc='lower left', fontsize=8.5)
    ax1.set_aspect('equal')

    # 子图 (b): 168 个连续区域单元划分
    ax2.set_title("(b) 168 个连续区域单元划分与覆盖证据位掩码", fontsize=12, fontweight='bold', pad=10)
    omega2 = patches.Circle([0, 0], 1800, edgecolor='red', facecolor='none', linewidth=2)
    ax2.add_patch(omega2)

    # 绘制 7 个主扇区与 6 个同心环 (0, 300, 600, 900, 1200, 1500, 1800)
    radii = [300, 600, 900, 1200, 1500, 1800]
    for r in radii:
        c_ring = patches.Circle([0, 0], r, edgecolor='gray', facecolor='none', linestyle=':', alpha=0.6)
        ax2.add_patch(c_ring)
        ax2.text(r - 120, 20, f'{r}m', fontsize=7, color='gray')

    # 绘制 7 个扇区分割线与 4 个角区分割线 (共 28 条径向线)
    for k in range(28):
        ang = 2.0 * math.pi * k / 28.0
        ax2.plot([0, 1800 * math.cos(ang)], [0, 1800 * math.sin(ang)], color='skyblue', linewidth=0.8, alpha=0.7)

    # 示意其中一个单元及其排除判定
    theta_demo1 = 0
    theta_demo2 = 2.0 * math.pi / 28.0
    r_demo1, r_demo2 = 600, 900
    wedge_cell = patches.Wedge([0, 0], r_demo2, math.degrees(theta_demo1), math.degrees(theta_demo2),
                               width=r_demo2 - r_demo1, edgecolor='crimson', facecolor='gold', alpha=0.8, linewidth=2,
                               label='典型区域单元 $T$ ($7\\times4\\times6=168$)')
    ax2.add_patch(wedge_cell)

    # 标注判定公式
    ax2.annotate('连续覆盖充分判定：\n$M(p, T) = \\max_{x\\in T}\\|x-p\\| \\leq q 1000$m\n若成立且该频道无信号，置位1位Bitmask',
                 xy=(750 * math.cos(math.pi/28), 750 * math.sin(math.pi/28)), xytext=(200, 1200),
                 arrowprops=dict(facecolor='darkred', shrink=0.08, width=1.5, headwidth=6),
                 fontsize=8.5, bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.9))

    ax2.set_xlim(-2100, 2100)
    ax2.set_ylim(-2100, 2100)
    ax2.set_xlabel("X 坐标 (米)", fontsize=10)
    ax2.set_ylabel("Y 坐标 (米)", fontsize=10)
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.legend(loc='lower left', fontsize=8.5)
    ax2.set_aspect('equal')

    plt.tight_layout()
    fig_path = os.path.join("figures", "fig3_p3_topology.png")
    plt.savefig(fig_path)
    plt.close()
    print(f"Generated: {fig_path}")

# ==============================================================================
# 4. 图4：问题四 25点32三角形覆盖网格与凸包包含特性
# ==============================================================================
def generate_fig4():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 6))

    # 子图 (a): 25点 32 三角形几何拓扑
    ax1.set_title("(a) 问题四 25 点 32 三角形固定保障网格布局", fontsize=12, fontweight='bold', pad=10)
    omega = patches.Circle([0, 0], 1800, edgecolor='red', facecolor='none', linewidth=2, linestyle='--', label='搜索圆域 $\\Omega$ ($R=1800$m)')
    ax1.add_patch(omega)

    # 构造点集: O, A_i (i=0..7), B_k (k=0..15)
    O = np.array([0.0, 0.0])
    A = [999.0 * np.array([math.cos(i * math.pi / 4.0), math.sin(i * math.pi / 4.0)]) for i in range(8)]
    B = [1840.0 * np.array([math.cos(k * math.pi / 8.0), math.sin(k * math.pi / 8.0)]) for k in range(16)]

    # 绘制 32 个三角形
    triangles = []
    for i in range(8):
        triangles.append((O, A[i], A[(i + 1) % 8]))
        triangles.append((A[i], B[2 * i], B[(2 * i + 1) % 16]))
        triangles.append((A[i], B[(2 * i + 1) % 16], A[(i + 1) % 8]))
        triangles.append((A[(i + 1) % 8], B[(2 * i + 1) % 16], B[(2 * i + 2) % 16]))

    for tri in triangles:
        t_patch = patches.Polygon(tri, closed=True, edgecolor='royalblue', facecolor='aliceblue', alpha=0.4, linewidth=1.2)
        ax1.add_patch(t_patch)

    # 绘制点
    ax1.plot(0, 0, 'go', markersize=8, label='中心原点 $O(0,0)$')
    for i, pt in enumerate(A):
        ax1.plot(pt[0], pt[1], 'bs', markersize=6)
        if i == 0:
            ax1.plot(pt[0], pt[1], 'bs', markersize=6, label='内层 8 点 $A_i$ ($R=999$m)')
    for k, pt in enumerate(B):
        ax1.plot(pt[0], pt[1], 'm^', markersize=6)
        if k == 0:
            ax1.plot(pt[0], pt[1], 'm^', markersize=6, label='外层 16 点 $B_k$ ($R=1840$m)')

    # 外层正十六边形边界
    poly_b = patches.Polygon(B, closed=True, edgecolor='purple', facecolor='none', linewidth=1.8, linestyle=':', label='外层正十六边形 (内切圆 $R=1804.6$m)')
    ax1.add_patch(poly_b)

    ax1.set_xlim(-2200, 2200)
    ax1.set_ylim(-2200, 2200)
    ax1.set_xlabel("X 坐标 (米)", fontsize=10)
    ax1.set_ylabel("Y 坐标 (米)", fontsize=10)
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.legend(loc='lower left', fontsize=8.5)
    ax1.set_aspect('equal')

    # 子图 (b): 未知朝向定向源凸包覆盖定理证明
    ax2.set_title("(b) 未知朝向定向源不漏源几何保证：$x \\in \\operatorname{conv}(Q_j(x))$", fontsize=12, fontweight='bold', pad=10)
    
    # 放大展示单个三角形内部任意点的凸包特性
    T_A = np.array([300, 400])
    T_B = np.array([900, 700])
    T_C = np.array([450, 1100])
    
    tri_demo = patches.Polygon([T_A, T_B, T_C], closed=True, edgecolor='navy', facecolor='powderblue', alpha=0.3, linewidth=2.5, label='三角形单元 $\\Delta V_1 V_2 V_3$ (边长 $\\leq q 999$m)')
    ax2.add_patch(tri_demo)

    # 目标点 x 在三角形内
    x_src = np.array([550, 720])
    ax2.plot(x_src[0], x_src[1], 'r*', markersize=14, label='候选定向源 $x$')

    # 绘制定向源的朝向与 180° 辐射半平面 (辐射方向法向量 n)
    phi = math.radians(130)
    d_vec = np.array([math.cos(phi), math.sin(phi)])
    n_vec = np.array([-math.sin(phi), math.cos(phi)])
    ax2.arrow(x_src[0], x_src[1], 200 * d_vec[0], 200 * d_vec[1], head_width=25, head_length=35, fc='red', ec='red', linewidth=2)
    ax2.text(x_src[0] + 100, x_src[1] - 80, '未知朝向 $\\vec{d}$', color='red', fontsize=10, fontweight='bold')

    # 辐射半平面覆盖半圆
    ax2.plot([x_src[0] - 600*n_vec[0], x_src[0] + 600*n_vec[0]], 
             [x_src[1] - 600*n_vec[1], x_src[1] + 600*n_vec[1]], 'r--', linewidth=1.5, label='辐射边界线 $(x-p)\\cdot \\vec{d} = 0$')

    # 顶点标注与距离圆
    ax2.plot(T_A[0], T_A[1], 'bo', markersize=8)
    ax2.text(T_A[0] - 80, T_A[1] - 30, '$V_1$', fontsize=11, fontweight='bold')
    ax2.plot(T_B[0], T_B[1], 'bo', markersize=8)
    ax2.text(T_B[0] + 20, T_B[1] - 20, '$V_2$', fontsize=11, fontweight='bold')
    ax2.plot(T_C[0], T_C[1], 'bo', markersize=8)
    ax2.text(T_C[0] - 20, T_C[1] + 25, '$V_3$', fontsize=11, fontweight='bold')

    # 标注核心理论
    ax2.annotate('【数学定理保证】：\n任意 $x \\in \\Delta V_1 V_2 V_3$，由于三边长 $\\leq q 999$m，\n故三顶点均满足 $\\|V_k - x\\| \\leq q 999 < 1000$m。\n由于 $x \\in \\operatorname{conv}(V_1, V_2, V_3)$，无论朝向为何，\n在 180° 前向辐射半平面内必存在至少一个顶点！\n$\\Rightarrow$ 绝不会遗漏任何未知朝向干扰源！',
                 xy=(x_src[0], x_src[1]), xytext=(150, 200),
                 arrowprops=dict(facecolor='darkred', shrink=0.08, width=1.5, headwidth=6),
                 fontsize=9.5, bbox=dict(boxstyle='round,pad=0.4', facecolor='lightyellow', alpha=0.9))

    ax2.set_xlim(100, 1100)
    ax2.set_ylim(150, 1250)
    ax2.set_xlabel("X 坐标 (米)", fontsize=10)
    ax2.set_ylabel("Y 坐标 (米)", fontsize=10)
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.legend(loc='upper left', fontsize=8.5)
    ax2.set_aspect('equal')

    plt.tight_layout()
    fig_path = os.path.join("figures", "fig4_p4_topology.png")
    plt.savefig(fig_path)
    plt.close()
    print(f"Generated: {fig_path}")

# ==============================================================================
# 5. 图5：问题三与问题四版本 B 与版本 C 基准测试性能对比
# ==============================================================================
def generate_fig5():
    import csv
    
    # 读取 P3 与 P4 真实测试数据
    p3_cases, p3_b_t, p3_c_t, p3_saved = [], [], [], []
    p3_path = os.path.join("results", "p3_benchmark_results.csv")
    with open(p3_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p3_cases.append(row['Case_ID'])
            p3_b_t.append(float(row['B_T_virtual_s']))
            p3_c_t.append(float(row['C_T_virtual_s']))
            p3_saved.append(float(row['Time_Saved_s']))

    p4_cases, p4_b_t, p4_c_t, p4_saved = [], [], [], []
    p4_path = os.path.join("results", "p4_benchmark_results.csv")
    with open(p4_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p4_cases.append(row['Case_ID'])
            p4_b_t.append(float(row['B_T_virtual_s']))
            p4_c_t.append(float(row['C_T_virtual_s']))
            p4_saved.append(float(row['Time_Saved_s']))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    # 子图 (a): 问题三耗时与节省
    x_idx = np.arange(len(p3_cases))
    width = 0.35
    ax1.set_title("(a) 问题三：版本 B (基线) 与版本 C (主方案) 虚拟总耗时对比", fontsize=11, fontweight='bold', pad=10)
    ax1.bar(x_idx - width/2, p3_b_t, width, label='版本 B (固定基线)', color='steelblue', alpha=0.85)
    ax1.bar(x_idx + width/2, p3_c_t, width, label='版本 C (滚动重排主方案)', color='darkorange', alpha=0.85)
    
    # 折线标示时间节省
    ax1_twin = ax1.twinx()
    ax1_twin.plot(x_idx, p3_saved, 'r-o', linewidth=2, markersize=6, label='时间节省 $\\Delta T$ (秒)')
    ax1_twin.axhline(0, color='gray', linestyle=':', linewidth=1)
    ax1_twin.set_ylabel('节约时间 (秒)', color='red', fontsize=10)
    ax1_twin.tick_params(axis='y', labelcolor='red')

    ax1.set_xticks(x_idx)
    labels = [c.replace("P3-", "") for c in p3_cases]
    ax1.set_xticklabels(labels, rotation=30, fontsize=8.5)
    ax1.set_ylabel("虚拟总耗时 $T$ (秒)", fontsize=10)
    ax1.grid(True, linestyle='--', alpha=0.4, axis='y')
    ax1.legend(loc='upper left', fontsize=8.5)
    ax1_twin.legend(loc='upper right', fontsize=8.5)

    # 子图 (b): 问题四耗时与节省
    ax2.set_title("(b) 问题四：版本 B (基线) 与版本 C (主方案) 虚拟总耗时对比", fontsize=11, fontweight='bold', pad=10)
    ax2.bar(x_idx - width/2, p4_b_t, width, label='版本 B (固定基线)', color='steelblue', alpha=0.85)
    ax2.bar(x_idx + width/2, p4_c_t, width, label='版本 C (滚动重排主方案)', color='forestgreen', alpha=0.85)

    ax2_twin = ax2.twinx()
    ax2_twin.plot(x_idx, p4_saved, 'r-s', linewidth=2, markersize=6, label='时间节省 $\\Delta T$ (秒)')
    ax2_twin.axhline(0, color='gray', linestyle=':', linewidth=1)
    ax2_twin.set_ylabel('节约时间 (秒)', color='red', fontsize=10)
    ax2_twin.tick_params(axis='y', labelcolor='red')

    ax2.set_xticks(x_idx)
    labels_p4 = [c.replace("P4-", "") for c in p4_cases]
    ax2.set_xticklabels(labels_p4, rotation=30, fontsize=8.5)
    ax2.set_ylabel("虚拟总耗时 $T$ (秒)", fontsize=10)
    ax2.grid(True, linestyle='--', alpha=0.4, axis='y')
    ax2.legend(loc='upper left', fontsize=8.5)
    ax2_twin.legend(loc='upper right', fontsize=8.5)

    plt.tight_layout()
    fig_path = os.path.join("figures", "fig5_benchmark_comparison.png")
    plt.savefig(fig_path)
    plt.close()
    print(f"Generated: {fig_path}")

# ==============================================================================
# 6. 图6：全局协同技术路线与证据链架构图
# ==============================================================================
def generate_fig6():
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_title("无线电干扰源探测、定位与清除总体技术路线与证据链闭环体系", fontsize=13, fontweight='bold', pad=15)
    ax.axis('off')

    # 定义各个模块矩形与文本
    boxes = [
        {"xy": (0.05, 0.72), "w": 0.25, "h": 0.20, "fc": "#E3F2FD", "ec": "#1976D2",
         "title": "【证据链与状态机】", 
         "text": "- 频道状态：UNKNOWN/FOUND/CLEARED/ABSENT\n- 完备终止准则：$K=16$ 或 20 频道全结\n- 虚拟时间账本：严格无重计与幂等保护"},
        
        {"xy": (0.38, 0.72), "w": 0.25, "h": 0.20, "fc": "#E8F5E9", "ec": "#388E3C",
         "title": "【P1 几何与安全清除】", 
         "text": "- 示向线半平面交 $\\rightarrow$ 交会多边形 $C$\n- 旋转卡壳算直径 $D$ 与 Welzl MEC $\\rho(C)$\n- 清除安全充分条件：$\\rho(C) \\leq q 20$ 米"},
        
        {"xy": (0.71, 0.72), "w": 0.25, "h": 0.20, "fc": "#FFF3E0", "ec": "#F57C00",
         "title": "【P2 决策与候选域】", 
         "text": "- 充分候选域 $\\Gamma_0$ (三圆交集)\n- 先验场景抽样与期望代价 $J_2(q)$\n- 确定最优第二点与近优区域 $R_{30}$"},
        
        {"xy": (0.05, 0.38), "w": 0.40, "h": 0.24, "fc": "#F3E5F5", "ec": "#7B1FA2",
         "title": "【在线保守网格与局部单步决策器】", 
         "text": "- 21779 局部保守网格单元 ($h_g=2$m, $d_g=1.414$m)，保证真位置不漏\n- 预设 225 中心基础有限覆盖清除计划，确保必在有限动作内收敛\n- 单步预期收益对比：覆盖清除 vs 补测后清除 (门槛 $\\Delta J \\geq q 5$s)\n- 严格不可逆停止规则：累计补测 $\\leq q 12$ 次或 $\\leq q 600$s 强制清除"},
        
        {"xy": (0.55, 0.38), "w": 0.41, "h": 0.24, "fc": "#FBE9E7", "ec": "#D84315",
         "title": "【P3/P4 固定保障覆盖拓扑】", 
         "text": "- P3 全向源：7 点 1000m 圆覆盖 $\\Omega$ + 168 连续区域单元位掩码\n- P4 未知朝向定向源：25 点 32 三角形拓扑，凸包条件 $x \\in \\operatorname{conv}(Q_j)$\n- 停靠点按需批量扫频，中途补测点关闭全扫防止开销爆炸"},
        
        {"xy": (0.15, 0.06), "w": 0.70, "h": 0.22, "fc": "#FFFDE7", "ec": "#FBC02D",
         "title": "【全局路径调度与双版本验收】", 
         "text": "- 版本 B (稳定基线)：固定拓扑巡回 + 发现即响应，高密度下贪心收敛快\n- 版本 C (主方案)：剩余搜索点与已发现目标联合开放 TSP，滚动 2-opt 重排\n- 三大不变量数学证明 + 宽松虚拟上限 (15.3万秒 < 36万秒) + 现实耗时 (<1秒 < 1200秒)"}
    ]

    for b in boxes:
        rect = patches.FancyBboxPatch(b["xy"], b["w"], b["h"], boxstyle="round,pad=0.015",
                                      facecolor=b["fc"], edgecolor=b["ec"], linewidth=2)
        ax.add_patch(rect)
        ax.text(b["xy"][0] + b["w"]/2.0, b["xy"][1] + b["h"] - 0.04, b["title"], 
                ha='center', va='center', fontsize=11, fontweight='bold', color=b["ec"])
        ax.text(b["xy"][0] + 0.015, b["xy"][1] + b["h"]/2.0 - 0.02, b["text"], 
                ha='left', va='center', fontsize=9, linespacing=1.4)

    # 绘制连接箭头
    ax.annotate("", xy=(0.25, 0.62), xytext=(0.18, 0.72),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
    ax.annotate("", xy=(0.25, 0.62), xytext=(0.50, 0.72),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
    ax.annotate("", xy=(0.35, 0.62), xytext=(0.80, 0.72),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
    ax.annotate("", xy=(0.75, 0.62), xytext=(0.75, 0.72),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
    ax.annotate("", xy=(0.50, 0.28), xytext=(0.30, 0.38),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
    ax.annotate("", xy=(0.50, 0.28), xytext=(0.75, 0.38),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))

    plt.tight_layout()
    fig_path = os.path.join("figures", "fig6_tech_roadmap.png")
    plt.savefig(fig_path)
    plt.close()
    print(f"Generated: {fig_path}")


if __name__ == "__main__":
    print("开始生成论文全套图件...")
    generate_fig1()
    generate_fig2()
    generate_fig3()
    generate_fig4()
    generate_fig5()
    generate_fig6()
    print("全部 6 个图件生成成功！已存入 figures/ 目录。")
