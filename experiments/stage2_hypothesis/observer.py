"""
observer.py —— 只记录、不干预的驱动包装（阶段2 的在线观测来源）

作用：把真实发生过的 measure / clear 动作与**实际反馈**逐条记录下来，
供臂 C 的假设模型读取"历史阳性/阴性观测"。

红线：本包装器不做任何决策、不改任何位置、不返回任何额外信息给引擎；
      它只是把已经发生的交互抄一份。
"""

from __future__ import annotations


class RecordingObserverDriver:
    def __init__(self, inner):
        self._inner = inner
        self.records = []          # 全部动作
        self.measures = []         # 仅 measure，按时间顺序

    # ---------------- 驱动接口 ----------------
    def enter(self):
        r = self._inner.enter()
        self.records.append({"kind": "enter", "t": r.get("virtual_time_s")})
        return r

    def measure(self, pos, channel):
        r = self._inner.measure(pos, channel)
        rec = {
            "kind": "measure",
            "pos": (round(float(pos[0]), 4), round(float(pos[1]), 4)),
            "channel": int(channel),
            "result": r.get("measure_result"),
            "svd": r.get("svd_deg"),
            "t": r.get("virtual_time_s"),
        }
        self.records.append(rec)
        self.measures.append(rec)
        return r

    def clear(self, pos, channel):
        r = self._inner.clear(pos, channel)
        self.records.append({
            "kind": "clear",
            "pos": (round(float(pos[0]), 4), round(float(pos[1]), 4)),
            "channel": int(channel),
            "result": r.get("clear_result"),
            "t": r.get("virtual_time_s"),
        })
        return r

    def exit(self):
        r = self._inner.exit()
        self.records.append({"kind": "exit", "t": r.get("virtual_time_s")})
        return r

    # ---------------- 给假设模型用的历史观测 ----------------
    def history(self, channel: int):
        """该频道到当前为止的全部观测（含发现前在搜索点上的阴性观测）"""
        out = []
        for rec in self.measures:
            if rec["channel"] != channel:
                continue
            res = rec["result"]
            if res == "direction":
                out.append({"kind": "direction", "p": rec["pos"], "svd": rec["svd"]})
            elif res == "no_signal":
                out.append({"kind": "no_signal", "p": rec["pos"], "svd": None})
            elif res == "near":
                out.append({"kind": "near", "p": rec["pos"], "svd": None})
        return out

    def count_history(self, channel: int):
        h = self.history(channel)
        return {
            "n_total": len(h),
            "n_direction": sum(1 for x in h if x["kind"] == "direction"),
            "n_no_signal": sum(1 for x in h if x["kind"] == "no_signal"),
            "n_near": sum(1 for x in h if x["kind"] == "near"),
        }
