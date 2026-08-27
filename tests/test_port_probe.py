"""端口预检与占用友好提示测试(v0.5.1):probe_port 三态 + cmd_start 分支。

背景:用户 `llm-sanitizer start` 遇端口占用时裸抛 traceback("千奇百怪的问题"之一)。
v0.5.1 改为:启动前探测端口归属(self=已在运行 / other=被其他程序占 / None=空闲),
给出可操作中文提示;新增 start --port / --dashboard-port。
"""

import contextlib
import io
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _OtherHandler(BaseHTTPRequestHandler):
    server_version = "OtherService/1.0"

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"other")
        self.wfile.flush()

    def log_message(self, *a):
        pass


class TestProbePort(unittest.TestCase):
    """probe_port 三态:空闲 None / 他服务 other / 自家网关 self。"""

    def test_free_port_is_none(self):
        from llm_sanitizer import gateway

        self.assertIsNone(gateway.probe_port(_free_port()))

    def test_other_service_is_other(self):
        from llm_sanitizer import gateway

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _OtherHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual(gateway.probe_port(srv.server_address[1]), "other")
        finally:
            srv.shutdown()

    def test_own_gateway_is_self(self):
        from llm_sanitizer import gateway

        srv = gateway.create_gateway_server(port=_free_port())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual(gateway.probe_port(srv.server_address[1]), "self")
        finally:
            srv.shutdown()


class TestCmdStartPortChecks(unittest.TestCase):
    """cmd_start 预检分支:已在运行 / 被占 / 看板被占 / 正常启动。"""

    def setUp(self):
        self._home = tempfile.mkdtemp(prefix="llms_home_")
        self._env = mock.patch.dict(
            os.environ,
            {
                "LLM_SANITIZER_HOME": self._home,
                "LLM_SANITIZER_PORT": str(_free_port()),
                "LLM_SANITIZER_DASHBOARD_PORT": str(_free_port()),
            },
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        from llm_sanitizer import cli

        self.cli = cli

    def _run_start(self, probes):
        args = SimpleNamespace(port=None, dashboard_port=None)
        buf = io.StringIO()
        with mock.patch.object(self.cli, "_probe_port", side_effect=probes), \
             contextlib.redirect_stdout(buf):
            self.cli.cmd_start(args)
        return buf.getvalue()

    def test_already_running_hint(self):
        out = self._run_start(["self"])
        self.assertIn("已在运行", out)
        self.assertIn("status", out)
        self.assertNotIn("Traceback", out)

    def test_other_program_occupies_hint(self):
        out = self._run_start(["other"])
        self.assertIn("已被其他程序占用", out)
        self.assertIn("--port", out)

    def test_dashboard_occupied_hint(self):
        out = self._run_start([None, "other"])
        self.assertIn("看板端口", out)
        self.assertIn("--dashboard-port", out)

    def test_normal_start(self):
        """全空闲:正常启动并打印地址;Ctrl+C 退出不崩。"""

        class FakeEvent:
            def is_set(self):
                return False

            def wait(self):
                raise KeyboardInterrupt()

        class FakeServer:
            def serve_forever(self):
                pass

            def shutdown(self):
                pass

        buf = io.StringIO()
        with mock.patch.object(self.cli, "_probe_port", side_effect=[None, None]), \
             mock.patch.object(self.cli.gateway, "create_gateway_server",
                               return_value=FakeServer()), \
             mock.patch.object(self.cli.dashboard, "create_dashboard_server",
                               return_value=FakeServer()), \
             mock.patch.object(self.cli.threading, "Event", FakeEvent), \
             contextlib.redirect_stdout(buf):
            self.cli.cmd_start(SimpleNamespace(port=None, dashboard_port=None))
        out = buf.getvalue()
        self.assertIn("网关  http://127.0.0.1:", out)
        self.assertIn("看板  http://127.0.0.1:", out)

    def test_start_with_explicit_ports(self):
        """--port/--dashboard-port 生效:create_*_server 收到指定端口。"""

        class FakeEvent:
            def is_set(self):
                return False

            def wait(self):
                raise KeyboardInterrupt()

        class FakeServer:
            def serve_forever(self):
                pass

            def shutdown(self):
                pass

        gw_port, db_port = _free_port(), _free_port()
        with mock.patch.object(self.cli, "_probe_port", side_effect=[None, None]), \
             mock.patch.object(self.cli.gateway, "create_gateway_server",
                               return_value=FakeServer()) as m_gw, \
             mock.patch.object(self.cli.dashboard, "create_dashboard_server",
                               return_value=FakeServer()) as m_db, \
             mock.patch.object(self.cli.threading, "Event", FakeEvent), \
             contextlib.redirect_stdout(io.StringIO()):
            self.cli.cmd_start(SimpleNamespace(port=gw_port, dashboard_port=db_port))
        self.assertEqual(m_gw.call_args.kwargs.get("port"), gw_port)
        self.assertEqual(m_db.call_args.kwargs.get("port"), db_port)


if __name__ == "__main__":
    unittest.main()
