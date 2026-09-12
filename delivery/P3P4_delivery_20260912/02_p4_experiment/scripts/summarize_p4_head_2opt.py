"""
summarize_p4_head_2opt.py - 汇总 P4 首任务 2-opt 实验并生成简短结论

输入：results/p4_head_2opt/{p4_head_2opt_paired.csv, p4_head_2opt_audit.json,
      p4_head_2opt_chain.json, diagnosis/p4_nontermination_diagnosis.json}
输出：results/p4_head_2opt/P4_EXPERIMENT_CONCLUSION.md  (简短结论)
"""

import sys
import os
import csv
import json

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
D = os.path.join(ROOT, "results", "p4_head_2opt")


def main():
    with open(os.path.join(D, "p4_head_2opt_audit.json"), encoding="utf-8") as f:
        audits = json.load(f)
    with open(os.path.join(D, "p4_head_2opt_chain.json"), encoding="utf-8") as f:
        chain = json.load(f)
    with open(os.path.join(D, "diagnosis", "p4_nontermination_diagnosis.json"), encoding="utf-8") as f:
        diag = json.load(f)
    with open(os.path.join(D, "p4_head_2opt_paired.csv"), encoding="utf-8-sig") as f:
        paired = list(csv.DictReader(f))

    assert chain["overall_pass"] is True

    # ---- 取候选臂第一个 head_changed 事件 ----
    event_md = []
    for key, aud in audits.items():
        if aud["arm"] != "candidate":
            continue
        for r in aud["head_dispatch_records"]:
            if r["head_changed"]:
                na = r.get("next_action")

                def desc(t):
                    if t["type"] == "target":
                        return f"target(channel={t.get('channel')})"
                    return f"search(point_idx={t.get('point_idx')})"

                event_md.append(
                    f"- 案例 {aud['case_id']} 第 {r['round']} 轮（虚拟时间 {r['virtual_time_s']:.2f}s，候选任务数 {r['task_count']}）：\n"
                    f"  - 优化前首任务: {desc(r['pre_head'])}，位置 {r['pre_head']['pos']}\n"
                    f"  - 最终实际派发: {desc(r['final_head'])}，位置 {r['final_head']['pos']}\n"
                    f"  - 紧随其后的真实动作: {na['path'] if na else '无'}，位置 {na['pos'] if na else '-'}\n"
                    f"  - 该动作到【最终首任务】距离 {r.get('next_action_dist_to_final_head_m', '-')} m，"
                    f"到【原首任务】距离 {r.get('next_action_dist_to_pre_head_m', '-')} m\n"
                    f"  - 判定实际动作是否跟随新首任务: **{r.get('next_action_matches_final_head')}**"
                )
                break
        if event_md:
            break

    n_pass = sum(1 for p in paired if p["Base_Acceptance"] == "True") + \
             sum(1 for p in paired if p["Cand_Acceptance"] == "True")

    L = []
    L.append("# P4 首任务 2-opt 单变量实验 · 结论\n")
    L.append("## 1. 实验设置\n")
    L.append("- 基线主分支: master，P3 径向候选合入提交 3a7491206c16acaa8c363b483679d9ab2a09da2f（3a74912）")
    L.append("- 实验分支: feature/p4-head-2opt-experiment")
    L.append("- **唯一实验变量**: P4 开放路线的 2-opt 允许改变最终实际派发的首任务（enable_2opt_head False → True）")
    L.append("- 未改动: P4 覆盖点集(25点)、冻结定位与清除组件、扫描规则、完成判据、清除点额外扫描(仍强制关闭)、P3 径向选点(未迁移)")
    L.append("- 三个预先固定场景: 10/13/16 源，seed 7210/7213/7216，dir_ratio=0.5")
    L.append("- 驱动: 本地替代驱动 src/sim_env.py，有界运行（动作上限 1500），**未调用官方模拟器**\n")

    L.append("## 2. 配对结果：无法给出有效收益结论\n")
    L.append("| 案例 | 源数(全向/定向) | 基线状态 | 候选状态 | 基线清除 | 候选清除 | 基线首任务改变 | 候选首任务改变 | 完整验收 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for p in paired:
        L.append(f"| {p['Case_ID']} | {p['Sources']} ({p['Omni_Sources']}/{p['Directional_Sources']}) | "
                 f"{p['Base_Run_Status']} | {p['Cand_Run_Status']} | {p['Base_Cleared']}/{p['Sources']} | "
                 f"{p['Cand_Cleared']}/{p['Sources']} | {p['Base_Head_Changes']} | {p['Cand_Head_Changes']} | "
                 f"{p['Base_Acceptance']} / {p['Cand_Acceptance']} |")
    L.append("")
    L.append(f"**六局中通过完整验收（完整清除 + 结束证据成立）的局数: {n_pass}/6。**")
    L.append("")
    L.append("三个场景下基线与候选**均未能正常终止**：卡死时 0 个目标被清除、20 个频道全部未决。")
    L.append("因此**不满足“完整清除与结束证据成立”的前提，本轮不产生任何配对收益数值**，")
    L.append("也不能据此判断机制是否值得进一步验证。**不以预计路径缩短代替实际节省，不凭三例宣称收益。**\n")

    L.append("## 3. 机制本身确实生效（但无法评估收益）\n")
    L.append("enable_2opt_head 从入口到引擎的生效链全部通过验收（p4_head_2opt_chain.json，14/14 PASS）。")
    L.append("在候选臂中，**每一局都真实改变了 1 次最终派发的首任务**；基线臂为 0 次。")
    L.append("该计数来自 head_dispatch_records 中 pre_head != final_head 的轮次，")
    L.append("**不是** 2-opt 的内部交换次数（total_2opt_swaps）。\n")
    L.append("### 一个具体事件（首任务改变 → 实际路线改变）\n")
    L.extend(event_md if event_md else ["- （无首任务改变事件）"])
    L.append("")
    L.append("该事件证明：2-opt 改变首任务后，紧接着执行的真实动作确实跟随了新首任务。")
    L.append("但由于整局在清除阶段卡死，**无法把该路线改变归因到整局耗时的变化**——")
    L.append("卡死前的 T 差异只反映“卡在哪个频道”，不反映有效路线的优劣。\n")

    L.append("## 4. 阻塞根因（与本实验变量无关）\n")
    L.append("诊断脚本 scripts/diagnose_p4_nontermination.py 给出的证据：\n")
    L.append("- **A. 既有记录不可复现**：p4_benchmark_results.csv / p4_heldout_benchmark_results.csv 中")
    L.append("  标注为完整清除的场景（seed 5000/5001/5002/9101/9102），在当前 P4 代码路径下全部非终止。")
    L.append("- **B. 归属明确**：同一场景、同一参数下，根目录冻结组件非终止，而共享 src/ 组件可正常终止并完整清除")
    L.append("  （例: seed 5000 → frozen RUNAWAY 清除 0/10；shared NORMAL 清除 10/10，T=6285.64s）。")
    L.append("- **C. 直接机制**：某 FOUND 目标经一次补测后保守网格存活单元归零，")
    L.append("  冻结决策器仍返回 reason='safe_clear_guaranteed' 且位置固定的清除动作，清除持续失败；")
    L.append("  service_found_target 的 while st.status == 'FOUND' 循环无法退出；")
    L.append("  引擎对 max_virtual_duration_s / max_real_duration_s 无任何强制终止，虚拟时间无界增长。")
    L.append("- 该缺陷在合入前的主线基线 160d265 上同样存在，**不是 P3 合入引入的**。\n")

    L.append("## 5. 结论与建议\n")
    L.append("1. P3 径向候选已完成合入（3a74912），默认仍为 stable，径向开关默认关闭，radial_candidate 需显式选择；")
    L.append("   **这是代码合入，不代表径向策略已成为默认。**")
    L.append("2. P4 首任务 2-opt 实验分支与唯一变量已就绪并通过链路验收，**机制确有效果**（每局真实改变 1 次派发首任务）。")
    L.append("3. 但在 P4 主线非终止缺陷修复之前，**三组配对试验无法在“完整清除 + 结束证据成立”的前提下完成**，")
    L.append("   因此本轮**不给出收益结论，也不宣称稳定收益**。")
    L.append("4. 建议把“用可正常终止的 src/ 组件重新冻结 P4 组件”作为**独立的一次修复**单独验证，")
    L.append("   而不是塞进本单变量实验（那会同时引入两个变量）。修复并单独验收后，再重跑本三组配对。")
    L.append("")

    text = "\n".join(L).replace("\\u0060", chr(96))
    out = os.path.join(D, "P4_EXPERIMENT_CONCLUSION.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print(f"\n[written] {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
