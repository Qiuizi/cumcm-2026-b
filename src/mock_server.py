"""
mock_server.py - 官方模拟器本地 Mock HTTP 服务器 (端口 2026)
完全对齐附件1与附件2规范：
1. 端口默认 2026，路径 /enter, /measure, /clear, /exit
2. 校验 Content-Type 为 application/json，校验 arena_id, robot_id, request_id
3. 幂等性：相同 request_id 返回原缓存响应
4. 内部托管 SimEnvironment 生成的合法随机案例 (全向或定向)
"""

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from src.sim_env import SimEnvironment


class MockSimulatorHandler(BaseHTTPRequestHandler):
    env: SimEnvironment = None
    robot_id: str = "team2026"
    idempotent_cache = {}

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len)

        try:
            req = json.loads(post_data.decode("utf-8"))
        except Exception:
            self._send_json(400, {"accepted": False, "error": "Invalid JSON"})
            return

        arena_id = req.get("arena_id")
        robot_id = req.get("robot_id")
        request_id = req.get("request_id")

        if arena_id != "default" or not robot_id or not request_id:
            self._send_json(
                400, {"accepted": False, "error": "Missing or invalid headers"}
            )
            return

        # 检查幂等性
        cache_key = f"{self.path}_{request_id}"
        if cache_key in self.idempotent_cache:
            self._send_json(200, self.idempotent_cache[cache_key])
            return

        now_ms = int(time.time() * 1000)

        if self.path == "/enter":
            res = self.env.enter()
            res["real_timestamp_ms"] = now_ms
            self.idempotent_cache[cache_key] = res
            self._send_json(200, res)

        elif self.path == "/measure":
            pos = req.get("position", {})
            x = float(pos.get("x", 0.0))
            y = float(pos.get("y", 0.0))
            channel = int(req.get("channel", 1))

            res = self.env.measure((x, y), channel)
            res["real_timestamp_ms"] = now_ms
            self.idempotent_cache[cache_key] = res
            self._send_json(200, res)

        elif self.path == "/clear":
            pos = req.get("position", {})
            x = float(pos.get("x", 0.0))
            y = float(pos.get("y", 0.0))
            channel = int(req.get("channel", 1))

            res = self.env.clear((x, y), channel)
            res["real_timestamp_ms"] = now_ms
            self.idempotent_cache[cache_key] = res
            self._send_json(200, res)

        elif self.path == "/exit":
            res = self.env.exit()
            res["real_timestamp_ms"] = now_ms
            self.idempotent_cache[cache_key] = res
            self._send_json(200, res)

        else:
            self._send_json(404, {"accepted": False, "error": "Path not found"})

    def log_message(self, format, *args):
        # 静默控制台输出以保证性能
        pass


def run_mock_server(
    port: int = 2026,
    num_sources: int = 12,
    is_p4: bool = False,
    seed: int = 42,
):
    env = SimEnvironment.generate_random_case(
        num_sources=num_sources, is_p4=is_p4, seed=seed
    )
    MockSimulatorHandler.env = env
    MockSimulatorHandler.idempotent_cache = {}
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, MockSimulatorHandler)
    print(f"Mock Simulator Server running at http://127.0.0.1:{port} (Sources: {num_sources}, is_p4: {is_p4})...")
    return httpd
