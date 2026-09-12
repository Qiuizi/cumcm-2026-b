"""
client_runner.py - 官方模拟器 HTTP 端口通信客户端与驱动器
既支持连接本地 Mock 服务器，又支持连接官方模拟器 (http://127.0.0.1:2026)
特性：
1. 严格遵守附件2规定的协议报文结构 (arena_id, robot_id, request_id)
2. 自动递增生成唯一 request_id；超时重试严格复用原 ID
3. 校验 accepted == True 与 HTTP 200
4. 单调记录现实运行时间与看门狗
5. 完整记录通信日志到 results/http_action_log.jsonl
"""

import json
import time
import os
import requests


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 【D2 最小修复】运行产物（HTTP 日志、审计、会话文件）的根目录解析。
#   背景：发布包重建会 `rmtree` 包目录 ⇒ 写在包内 results/ 的官方运行日志会被抹除。
#   规则：显式参数 > 环境变量 CUMCM_RUNS_DIR > 包内 runs_config.json > 默认 <PROJECT_ROOT>/results。
#   runs_config.json 里的 runs_dir 允许相对路径（相对 PROJECT_ROOT 解析），
#   发布包据此把默认日志指向**包外**的独立目录（重建不会触碰）。
RUNS_CONFIG_NAME = "runs_config.json"
RUNS_DIR_ENV = "CUMCM_RUNS_DIR"


def resolve_runs_dir(project_root: str = None, override: str = None) -> str:
    """解析运行产物根目录（日志/审计/会话文件都放在它下面）。"""
    root = os.path.abspath(project_root or PROJECT_ROOT)
    if override:
        return os.path.abspath(override)
    env = os.environ.get(RUNS_DIR_ENV)
    if env:
        return os.path.abspath(env)
    cfg_path = os.path.join(root, RUNS_CONFIG_NAME)
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            configured = (cfg or {}).get("runs_dir")
            if configured:
                if os.path.isabs(configured):
                    return os.path.abspath(configured)
                return os.path.abspath(os.path.join(root, configured))
        except (OSError, ValueError):
            pass                      # 配置损坏时退回默认，不因日志路径而中断运行
    return os.path.join(root, "results")



class HttpActionError(RuntimeError):
    """带分类的 HTTP 动作错误（便于上层如实标记"未完成"，不伪造 COMPLETED）"""

    def __init__(self, message: str, kind: str, path: str = None,
                 status_code: int = None, attempts: int = None):
        super().__init__(message)
        self.kind = kind                  # rejected | fatal_status | retry_exhausted
        self.path = path
        self.status_code = status_code
        self.attempts = attempts


class HttpSimDriver:
    # ---- 附件2 §5.3 错误分类（只影响失败分支，不改变正常动作序列）----
    # 可重试：动作未执行或执行结果不明，且同一 request_id + 同一内容具备幂等保护
    #   （§5.3：同一ID、同一内容返回第一次的完整响应，不重复移动/检测/清除/推进时间）
    RETRYABLE_STATUS = (429, 500)
    # 确定性错误：重试相同内容不可能成功，且**不得靠更换 request_id 掩盖内容冲突**
    #   400 结构错误 / 404 路径 / 405 方法 / 409 同一ID对应不同动作 / 413 体积 / 415 头
    FATAL_STATUS = (400, 404, 405, 409, 413, 415)

    STATUS_MEANING = {
        400: "请求结构错误（JSON语法/字段/范围）",
        404: "路径未知或不精确",
        405: "已知路径使用了非POST方法",
        409: "同一 request_id 对应了不同动作，或并发发送了不同动作",
        413: "请求体超过65536字节",
        415: "Content-Type 或 Content-Encoding 不受支持",
        429: "连接/无效流量保护触发，或本局幂等记录达到上限",
        500: "模拟器内部错误",
    }

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:2026",
        robot_id: str = "team2026",
        timeout_s: float = 10.0,
        log_file: str = None,
        runs_dir: str = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.robot_id = robot_id
        self.timeout_s = timeout_s
        # 【D2 最小修复】运行产物根目录（默认解析见 resolve_runs_dir）
        self.runs_dir = resolve_runs_dir(override=runs_dir)

        # 1. 默认快捷最新日志文件
        self.log_file = log_file or os.path.join(self.runs_dir, "http_action_log.jsonl")
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        with open(self.log_file, "w", encoding="utf-8") as f:
            pass

        # 2. 每局单独时间戳归档日志文件
        session_ts = time.strftime("%Y%m%d_%H%M%S")
        audit_dir = os.path.join(self.runs_dir, "audit_logs")
        os.makedirs(audit_dir, exist_ok=True)
        self.session_file = os.path.join(audit_dir, f"http_session_{session_ts}_{self.robot_id}.jsonl")
        with open(self.session_file, "w", encoding="utf-8") as f:
            pass

        self.abs_session_path = os.path.abspath(self.session_file)
        print(f"[PORT] 本局明文通信日志单独归档绝对路径: {self.abs_session_path}")

        self.req_seq = 0
        self.remaining_real_duration_s = 1200
        self.start_timestamp = 0.0

    def _require_accepted(self, path: str, res: dict):
        """
        附件2 §5.3 末条与 §12：**必须同时检查 HTTP 状态和 accepted**；
        `accepted=false` 表示动作**没有生效**，其 `virtual_time_s=0` **不是当前虚拟时刻**。

        这里直接抛错而不是返回，因此调用方（引擎）不会用 0 覆盖
        已知的虚拟时钟、当前位置或测量频道。
        """
        if res.get("accepted") is True:
            return res
        raise HttpActionError(
            f"{path} 未被执行（accepted=false）：动作没有生效；响应中的 virtual_time_s="
            f"{res.get('virtual_time_s')!r} 不是当前虚拟时刻 —— "
            f"不更新虚拟时钟 / 位置 / 测量频道。完整响应={res}",
            kind="rejected", path=path)

    def _next_request_id(self, prefix: str = "req") -> str:
        self.req_seq += 1
        return f"{prefix}-{self.req_seq:06d}"

    def _write_log_entry(self, entry: dict):
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(line)
        if self.log_file != self.session_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)

    def _write_diagnostic(self, path: str, payload: dict, attempt: int,
                          kind: str, detail: str = None, status_code: int = None):
        """
        诊断记录：把**已发出但未取得 HTTP 200 的请求**如实写入会话日志。

        必要性（本轮断点定位的直接结论）：原先只有 `status_code == 200` 才写日志，
        因此一旦某条请求拿不到 200，"会话日志停在上一成功请求"与"程序卡住"在事后
        完全无法区分。该记录**不改变任何请求内容、重试次数与计费**，
        `audit_http_action_log` 亦会因 `response.accepted` 缺失而跳过它。
        """
        entry = {
            "timestamp": time.time(),
            "path": path,
            "request": payload,
            "response": None,
            "diagnostic": kind,
            "attempt": attempt,
        }
        if detail is not None:
            entry["error"] = detail
        if status_code is not None:
            entry["status_code"] = status_code
        self._write_log_entry(entry)

    def _post_with_retry(self, path: str, payload: dict, max_retries: int = 3):
        """
        按附件2 §5.3 分类处理失败（**只改失败分支**，正常动作序列不变）：

        | 情形                                   | 处理 |
        |---|---|
        | 200（含 accepted 由调用方判定）         | 记录并返回 |
        | 网络超时/连接中断（无 JSON 体）        | 复用**原 request_id 与原请求内容**重试（§5.3 唯一允许的复用场景） |
        | 429 / 500（动作未执行，可重试）         | 退避后重试，**同样复用原 id 与原内容**（幂等保护保证不重复执行） |
        | 400/404/405/409/413/415（确定性错误）  | **立即失败，不重试、不换 id**（换 id 会掩盖内容/幂等冲突） |
        | 重试耗尽                               | 抛出 `HttpActionError(kind='retry_exhausted')` 并如实标记未完成 |
        """
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        body = json.dumps(payload)

        last_status = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, data=body, headers=headers, timeout=self.timeout_s)
            except requests.exceptions.RequestException as e:
                # 执行结果不明（连接被关闭、超时）：§5.3 允许复用原 id 与原内容重试
                print(f"[RETRY] 网络超时/连接中断 (尝试 {attempt}/{max_retries}): {e}")
                self._write_diagnostic(path, payload, attempt, "transport_error", detail=repr(e))
                if attempt < max_retries:
                    time.sleep(0.5)
                    continue
                break

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError as e:
                    # 200 但响应体不是合法 JSON：不得当作成功
                    self._write_diagnostic(path, payload, attempt, "malformed_json",
                                           detail=repr(e), status_code=200)
                    raise HttpActionError(
                        f"{path} 返回 200 但响应体不是合法 JSON：{e}",
                        kind="fatal_status", path=path, status_code=200, attempts=attempt)
                self._write_log_entry({
                    "timestamp": time.time(), "path": path,
                    "request": payload, "response": data,
                })
                return data          # accepted 由调用方按 §5.3 另行判定

            last_status = resp.status_code
            if resp.status_code in self.FATAL_STATUS:
                # 确定性错误：重试相同内容不可能成功；换 id 会掩盖内容/幂等冲突
                meaning = self.STATUS_MEANING.get(resp.status_code, "确定性错误")
                self._write_diagnostic(path, payload, attempt, "fatal_status",
                                       detail=(resp.text or "")[:500],
                                       status_code=resp.status_code)
                raise HttpActionError(
                    f"{path} 收到 HTTP {resp.status_code}（{meaning}）—— "
                    f"按附件2 §5.3 属确定性错误，不重试、不更换 request_id；"
                    f"请修正请求内容或 request_id 冲突后重发。",
                    kind="fatal_status", path=path,
                    status_code=resp.status_code, attempts=attempt)

            if resp.status_code in self.RETRYABLE_STATUS:
                meaning = self.STATUS_MEANING.get(resp.status_code, "可重试")
                print(f"[RETRY] HTTP {resp.status_code}（{meaning}）"
                      f" (尝试 {attempt}/{max_retries})")
                self._write_diagnostic(path, payload, attempt, "retryable_status",
                                       detail=(resp.text or "")[:500],
                                       status_code=resp.status_code)
                if attempt < max_retries:
                    time.sleep(0.5)
                    continue
                break

            # 未在附件2 §5.3 表2 中列出的状态码：保守按可重试处理，但仍有次数上限
            print(f"[RETRY] HTTP {resp.status_code} 未在附件2 §5.3 列表中 "
                  f"(尝试 {attempt}/{max_retries}): {resp.text[:200]}")
            self._write_diagnostic(path, payload, attempt, "unexpected_status",
                                   detail=(resp.text or "")[:500],
                                   status_code=resp.status_code)
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            break

        self._write_diagnostic(path, payload, max_retries, "retry_exhausted",
                               detail=f"no HTTP 200 after all attempts (last_status={last_status})",
                               status_code=last_status)
        print(f"[ABORT] {path} 在 {max_retries} 次尝试后仍未取得 HTTP 200 —— "
              f"本次运行**未完成**（已如实写入会话日志，未伪造完成）。")
        raise HttpActionError(
            f"HTTP 请求失败: {path}（{max_retries} 次尝试均未取得 HTTP 200"
            + (f"，最后状态码 {last_status}" if last_status else "，均为网络层失败") + "）",
            kind="retry_exhausted", path=path,
            status_code=last_status, attempts=max_retries)

    def enter(self):
        req_id = self._next_request_id("enter")
        payload = {
            "arena_id": "default",
            "robot_id": self.robot_id,
            "request_id": req_id,
        }
        res = self._post_with_retry("/enter", payload)
        if not res.get("accepted", False):
            err_msg = (
                f"\n{'='*75}\n"
                f"【模拟器拒绝接入告警】/enter 接口返回 accepted=false: {res}\n"
                f"排查建议：\n"
                f"  1. 队号未匹配：当前传入的是 robot_id='{self.robot_id}'，请通过命令行参数 --robot_id 或环境变量 ROBOT_ID 传入真实注册的参赛队号；\n"
                f"  2. 模拟器状态未就绪：官方模拟器可能尚未点击 '启动/准备' 或正处于上轮对局未重置状态；\n"
                f"  3. 端口已被其他服务占用。\n"
                f"{'='*75}"
            )
            print(err_msg)
            self._require_accepted("/enter", res)   # 抛 HttpActionError(kind='rejected')

        self.remaining_real_duration_s = res.get("remaining_real_duration_s", 1200)
        self.start_timestamp = time.time()
        print(f"[PORT] 成功进入目标区域！剩余可用现实运行时间: {self.remaining_real_duration_s} 秒")
        return res

    def measure(self, pos: tuple, channel: int):
        req_id = self._next_request_id("measure")
        payload = {
            "arena_id": "default",
            "robot_id": self.robot_id,
            "request_id": req_id,
            "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)},
            "channel": int(channel),
        }
        res = self._post_with_retry("/measure", payload)
        return self._require_accepted("/measure", res)

    def clear(self, pos: tuple, channel: int):
        req_id = self._next_request_id("clear")
        payload = {
            "arena_id": "default",
            "robot_id": self.robot_id,
            "request_id": req_id,
            "position": {"x": round(float(pos[0]), 2), "y": round(float(pos[1]), 2)},
            "channel": int(channel),
        }
        res = self._post_with_retry("/clear", payload)
        return self._require_accepted("/clear", res)

    def exit(self):
        req_id = self._next_request_id("exit")
        payload = {
            "arena_id": "default",
            "robot_id": self.robot_id,
            "request_id": req_id,
        }
        res = self._post_with_retry("/exit", payload)
        # §5.3 要求同时检查 HTTP 状态与 accepted：/exit 被拒时如实告警（不改变退出流程）
        if res.get("accepted") is not True:
            print(f"[WARN] /exit 未被执行（accepted=false）：{res} —— "
                  f"本次退出原因以模拟器侧记录为准，不由客户端事后声明。")
        elapsed = time.time() - self.start_timestamp
        print(f"[PORT] 成功调用 /exit 退出目标区域！本次程序实际运行时间: {elapsed:.2f} 秒")
        
        # 自动汇总五类耗时与退出耗时
        summary = audit_http_action_log(self.session_file)
        self.print_audit_summary(summary)
        return res

    def print_audit_summary(self, summary: dict):
        print("\n" + "=" * 65)
        print("【HTTP 通信计账与耗时分解审计报告 (唯一有效动作计账)】")
        print("=" * 65)
        print(f"归档日志绝对路径:         {summary['log_file_abs_path']}")
        print(f"有效唯一请求数:           {summary['unique_accepted_action_count']} 条 (重试重复请求已去重)")
        print(f"1. 移动耗时 (L/5):        {summary['movement_time_s']:.2f} 秒 (路程: {summary['total_move_dist_m']:.1f}m, 占比 {summary['movement_pct']:.1f}%)")
        print(f"2. 切频道耗时 (1s/次):    {summary['channel_switch_time_s']:.2f} 秒 (切换次数: {summary['channel_switch_count']})")
        print(f"3. 检测耗时 (5s/次):      {summary['measure_time_s']:.2f} 秒 (检测次数: {summary['measure_count']})")
        print(f"4. 失败清除耗时 (3s/次):  {summary['clear_fail_time_s']:.2f} 秒 (失败次数: {summary['clear_fail_count']})")
        print(f"5. 成功清除耗时 (5s/次):  {summary['clear_succ_time_s']:.2f} 秒 (成功清除: {summary['clear_succ_count']})")
        print("-" * 65)
        print(f"五类耗时计算总和:         {summary['total_accounted_virtual_time_s']:.2f} 秒")
        print(f"模拟器最终虚拟总耗时:     {summary['final_virtual_time_s']:.2f} 秒 (校核差值: {summary['accounting_discrepancy_s']:.4f} 秒)")
        print(f"最后一次成功清除至退出耗时: {summary['time_last_clear_to_exit_s']:.2f} 秒")
        print("=" * 65)


def audit_http_action_log(log_path: str) -> dict:
    """
    根据赛题规则对明文 HTTP 日志进行精确计账审计：
    1. 严格以 request_id 去重，只统计 accepted == True 的唯一有效动作
    2. 分解 5 类耗时：移动(L/5)、切频道(1s)、检测(5s)、清除失败(3s)、清除成功(5s)
    3. 计算最后一次成功清除到退出的耗时
    4. 核对计账总和与模拟器 virtual_time_s
    """
    import math

    abs_path = os.path.abspath(log_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"日志文件不存在: {abs_path}")

    seen_req_ids = set()
    valid_entries = []
    with open(abs_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            resp = entry.get("response") or {}
            if not resp.get("accepted"):
                continue

            req = entry.get("request", {})
            req_id = req.get("request_id")
            if req_id and req_id in seen_req_ids:
                # 忽略因超时重发产生的重复已被接收响应
                continue
            if req_id:
                seen_req_ids.add(req_id)
            valid_entries.append(entry)

    cur_pos = (0.0, 0.0)
    cur_channel = 1
    total_dist_m = 0.0
    t_move = 0.0
    t_switch = 0.0
    count_switch = 0
    t_measure = 0.0
    count_measure = 0
    t_clear_fail = 0.0
    count_clear_fail = 0
    t_clear_succ = 0.0
    count_clear_succ = 0

    last_succ_clear_vt = None
    final_vt = 0.0

    for e in valid_entries:
        p = e.get("path")
        req = e.get("request", {})
        resp = e.get("response") or {}
        vt = float(resp.get("virtual_time_s", 0.0))
        final_vt = max(final_vt, vt)

        if p == "/enter":
            cur_pos = (0.0, 0.0)
            cur_channel = 1

        elif p == "/measure":
            pos_dict = req.get("position", {})
            px = float(pos_dict.get("x", 0.0))
            py = float(pos_dict.get("y", 0.0))
            ch = int(req.get("channel", cur_channel))

            d = math.hypot(px - cur_pos[0], py - cur_pos[1])
            total_dist_m += d
            t_move += d / 5.0

            if ch != cur_channel:
                t_switch += 1.0
                count_switch += 1
                cur_channel = ch

            t_measure += 5.0
            count_measure += 1
            cur_pos = (px, py)

        elif p == "/clear":
            pos_dict = req.get("position", {})
            px = float(pos_dict.get("x", 0.0))
            py = float(pos_dict.get("y", 0.0))
            d = math.hypot(px - cur_pos[0], py - cur_pos[1])
            total_dist_m += d
            t_move += d / 5.0
            cur_pos = (px, py)

            c_res = resp.get("clear_result")
            if c_res == "success":
                t_clear_succ += 5.0
                count_clear_succ += 1
                last_succ_clear_vt = vt
            else:
                t_clear_fail += 3.0
                count_clear_fail += 1

        elif p == "/exit":
            final_vt = vt

    t_accounted = t_move + t_switch + t_measure + t_clear_fail + t_clear_succ
    move_pct = (t_move / t_accounted * 100.0) if t_accounted > 0 else 0.0

    if last_succ_clear_vt is not None:
        time_last_clear_to_exit = max(0.0, final_vt - last_succ_clear_vt)
    else:
        time_last_clear_to_exit = final_vt

    return {
        "log_file_abs_path": abs_path,
        "unique_accepted_action_count": len(valid_entries),
        "total_move_dist_m": round(total_dist_m, 2),
        "movement_time_s": round(t_move, 2),
        "movement_pct": round(move_pct, 2),
        "channel_switch_count": count_switch,
        "channel_switch_time_s": round(t_switch, 2),
        "measure_count": count_measure,
        "measure_time_s": round(t_measure, 2),
        "clear_fail_count": count_clear_fail,
        "clear_fail_time_s": round(t_clear_fail, 2),
        "clear_succ_count": count_clear_succ,
        "clear_succ_time_s": round(t_clear_succ, 2),
        "total_accounted_virtual_time_s": round(t_accounted, 2),
        "final_virtual_time_s": round(final_vt, 2),
        "accounting_discrepancy_s": round(abs(t_accounted - final_vt), 4),
        "time_last_clear_to_exit_s": round(time_last_clear_to_exit, 2),
    }

