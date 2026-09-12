"""
observer.py —— 只记录、不干预的驱动包装（候选版的在线观测来源 + 网格计数取证）

作用一：把真实发生过的 measure / clear 与**实际反馈**逐条记录，供预测器读取历史观测。
作用二（本阶段新增）：在每次驱动调用开始时快照"各频道安全网格的存活单元数"，
        从而可以事后精确区分三件事：
          ① no_signal 总次数
          ② 其中"该频道网格未收缩"的次数
          ③ 相对稳定基线减少的次数
        快照取的是调用开始时刻的计数；由于引擎在 measure 返回后才做裁剪，
        因此第 k 次测量的"测后计数"= 第 k+1 次调用开始时的快照。

红线：不做任何决策、不改任何位置、不向引擎返回任何额外信息。
"""

from __future__ import annotations


class RecordingObserverDriver:
    def __init__(self, inner, engine=None):
        self._inner = inner
        self.engine = engine            # 运行后再 attach 也可以
        self.records = []
        self.measures = []
        self.count_snapshots = []       # 每次调用开始时的 {channel: grid_count}

    def attach_engine(self, engine):
        self.engine = engine

    # ---------------- 网格计数快照 ----------------
    def _snapshot_counts(self):
        if self.engine is None:
            return None
        snap = {}
        for ch, st in self.engine.channels.items():
            g = getattr(st, "grid", None)
            snap[int(ch)] = (int(g.count()) if g is not None else None)
        return snap

    # ---------------- 驱动接口 ----------------
    def enter(self):
        r = self._inner.enter()
        self.records.append({"kind": "enter", "t": r.get("virtual_time_s")})
        return r

    def measure(self, pos, channel):
        self.count_snapshots.append(self._snapshot_counts())
        r = self._inner.measure(pos, channel)
        rec = {
            "kind": "measure",
            "pos": (round(float(pos[0]), 4), round(float(pos[1]), 4)),
            "channel": int(channel),
            "result": r.get("measure_result"),
            "svd": r.get("svd_deg"),
            "t": r.get("virtual_time_s"),
            "snapshot_idx": len(self.count_snapshots) - 1,
        }
        self.records.append(rec)
        self.measures.append(rec)
        return r

    def clear(self, pos, channel):
        self.count_snapshots.append(self._snapshot_counts())
        r = self._inner.clear(pos, channel)
        self.records.append({
            "kind": "clear",
            "pos": (round(float(pos[0]), 4), round(float(pos[1]), 4)),
            "channel": int(channel),
            "result": r.get("clear_result"),
            "t": r.get("virtual_time_s"),
            "snapshot_idx": len(self.count_snapshots) - 1,
        })
        return r

    def exit(self):
        self.count_snapshots.append(self._snapshot_counts())
        r = self._inner.exit()
        self.records.append({"kind": "exit", "t": r.get("virtual_time_s")})
        return r

    # ---------------- 给预测器用的历史观测 ----------------
    def history(self, channel: int):
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

    def grid_count_before(self, measure_rec):
        """该次测量开始前的网格计数（可能为 None）"""
        idx = measure_rec.get("snapshot_idx")
        if idx is None or idx >= len(self.count_snapshots):
            return None
        snap = self.count_snapshots[idx]
        return None if snap is None else snap.get(measure_rec["channel"])

    def grid_count_after(self, measure_rec):
        idx = measure_rec.get("snapshot_idx")
        if idx is None or idx + 1 >= len(self.count_snapshots):
            return None
        snap = self.count_snapshots[idx + 1]
        return None if snap is None else snap.get(measure_rec["channel"])

    # ---------------- 三件事的精确区分 ----------------
    def no_signal_census(self):
        """
        返回:
          no_signal_total            —— 全部 no_signal 测量次数
          no_signal_followup         —— 该频道**已发现之后**发生的 no_signal 测量次数
          no_signal_grid_exists      —— no_signal 发生时该频道已有安全网格的次数
          no_signal_grid_not_shrunk  —— 其中"测后网格计数未减少"的次数
          no_signal_grid_shrunk      —— 其中"测后网格计数减少"的次数
        """
        detected_t = {}
        for rec in self.measures:
            if rec["result"] in ("direction", "near"):
                detected_t.setdefault(rec["channel"], rec["t"])

        total = followup = grid_exists = not_shrunk = shrunk = 0
        for rec in self.measures:
            if rec["result"] != "no_signal":
                continue
            total += 1
            dt = detected_t.get(rec["channel"])
            if dt is not None and rec["t"] >= dt:
                followup += 1
            before = self.grid_count_before(rec)
            after = self.grid_count_after(rec)
            if before is None:
                continue
            grid_exists += 1
            if after is None or after >= before:
                not_shrunk += 1
            else:
                shrunk += 1
        return {
            "no_signal_total": total,
            "no_signal_followup": followup,
            "no_signal_grid_exists": grid_exists,
            "no_signal_grid_not_shrunk": not_shrunk,
            "no_signal_grid_shrunk": shrunk,
        }
