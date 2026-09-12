# 「文件被恢复为 HEAD」只读排查（本轮，未停用任何进程）

## 一、已确认的事实（有直接证据）

| # | 事实 | 证据 |
|---|---|---|
| 1 | `scripts/run_port_test.py` 被执行期间**两次**被恢复为与 HEAD **逐字节相同**的内容 | 第 1 次约 `00:15:42`：history_candidate 首次运行在打印完候选接线信息后崩于 `AttributeError: 'RecordingObserverDriver' object has no attribute 'session_file'`——该行已在新版删改；第 2 次约 `00:25`：验收第三局 R3 的日志出现**旧版** argparse 用法行 `[--profile {stable,radial_candidate}]` 与 `unrecognized arguments: --mock_seed --session_dir` |
| 2 | 同期**未跟踪文件全部完好** | `experiments/stage3_candidate/*`、`scratch/*`、`results/*` 下的新文件在两次回退中均未受影响（后续全部正常运行） |
| 3 | 现象是**间歇性**的，不是持续性的 | 第 3 次观测（约 30 分钟后）：`scripts/run_port_test.py` 仍为接线版，sha256 前 16 位 `230606087416c5f1`，与验收时记录值一致，**未再回退** |
| 4 | 排查时点无常规触发源 | `.git/hooks` 只有 `*.sample`（无活动钩子）；`git config core.hooksPath` 为空；`git stash list` 为空；无 OneDrive/Dropbox/Syncthing/坚果云等同步进程；无命令行含 `git` 的进程；无名称匹配 Sync/Backup/Git 的计划任务 |
| 5 | 工作区不在 OneDrive 目录内 | `OneDrive` / `OneDriveConsumer` = `C:\Users\123\OneDrive`；工作区在 `D:\桌面\...`；`D:\桌面\desktop.ini` 仅为 `[.ShellClassInfo]` 图标配置，无重定向条目 |
| 6 | `git reflog` 在回退时段内**没有** checkout / 分支移动记录 | `HEAD@{0}` 仍是 `badd8f6 ... packaging for the coverage redesign delivery`。**注意**：文件级 `git restore <path>` / `git checkout -- <path>` **不写 reflog**，因此这一条**不能排除** git 级恢复 |
| 7 | DSH 宿主（`@deepseek-ai/dsh`）未发现工作区文件恢复逻辑 | 只读搜索仅命中**会话**快照相关代码（`dsh-session*`、`validateRestoredSessionHeader`），与工作区文件无关 |
| 8 | 端口 2026 上已有一个用户侧服务在监听 | `jammers-simulator.exe`（`D:\Downloads\CUMCM2026B\Jammers-simulator-win64\Jammers-simulator\`），PID 36360，起始 `2026-09-12 10:29:40`，监听 `127.0.0.1:2026`（与「文件回退」无关，但对启动命令重要） |

## 二、推测（**未证实**，不作为结论）

- **最符合特征的机制**：某个外部代理在特定时刻对**已跟踪文件**执行了 git 级恢复
  （因为"内容 = HEAD 逐字节相同 + 只影响已跟踪文件 + 未跟踪文件完好"这三点同时成立）。
- 可能的来源（均**未**获得证据）：
  1. 用户侧 IDE / 插件或其它自动化工具的"从磁盘/版本库重载"行为；
  2. 某个周期性仓库清理/回滚动作；
  3. 其它进程对该仓库执行了 `git checkout` / `git restore`。
- **已排除/不支持**：git 钩子、`core.hooksPath`、同步客户端、计划任务、DSH 会话机制
  （§一 的 4/7 条）。

## 三、处置（不擅自停用未知进程）

1. **不宣称环境安全**：在无法确认来源的前提下，不把"工作区能长期保留修改"当作交付前提。
2. **把完整发布内容固化到独立目录**：`release/p4_history_candidate_v1/`
   —— 全部依赖自带（`src/`、冻结组件、`candidate/`），入口按 `__file__` 相对定位，
   **不依赖原实验工作区的任何路径**，也不调用 git。
3. **发布包自带校验**：`BUILD_INFO.json` 记录可运行文件指纹，入口启动时自检；
   `check_release.py` 可独立复核导入路径/指纹/模型参数/真值隔离/启动行为。
4. 仍保留幂等补丁 `scratch/apply_port_wiring.py` 与 `results/delivery/run_port_test_wiring.patch`，
   供需要在实验工作区临时复现时使用（**发布包本身不需要它**）。

## 四、对交付的影响

- 发布包位于**未跟踪目录**，未受两次回退影响；其"启动前后源码未变化"已用哈希前后比对验证：
  本次验收运行**未修改任何发布文件**（运行前后 20/20 源码文件哈希完全一致）；
  其后仅补写 2 个文档并刷新指纹清单，19 个代码/依赖文件哈希保持不变。
- 本排查**未**终止、未停用、未修改任何进程或系统配置。
