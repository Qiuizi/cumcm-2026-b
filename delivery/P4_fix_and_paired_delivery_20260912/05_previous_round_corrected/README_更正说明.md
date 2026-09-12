# 上一轮（修复前）六个失败运行 · 收益字段更正说明

上一轮 `results/p4_head_2opt/p4_head_2opt_paired.csv` 中，三组配对的 6 局全部未完成：
0 个目标清除、20 个频道未决、完整验收 False/False。

该文件中的 `Saved_T_s` 是由两臂在**动作上限处**的故障态虚拟时间相减得到，
只反映"卡死在哪个频道"，**不构成 2-opt 的性能测量**。

本次更正：

- `p4_head_2opt_paired_corrected.csv`：`Saved_T_s` 置为 **N/A**，
  原值移入 `Saved_T_s_original` 列，并新增 `Saved_T_s_Note` 说明；
  其余字段与原始动作数据一字未改。
- `ORIGINAL_p4_head_2opt_paired.csv`：原始文件原样保留，便于追溯。
- 原始动作日志（每局 1500 条）保存在上一轮交付包 `results/p4_head_2opt/action_logs/`，未被修改。
- 修复死循环带来的效果**不计入** 2-opt 收益；本轮 2-opt 收益只在同一修复版本的两臂之间比较。
