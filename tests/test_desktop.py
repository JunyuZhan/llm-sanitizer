"""桌面窗口模式测试(v0.5.3):后台已有服务时直接开窗,不重复起服务。

三种情形:
- probe=self(后台已有服务,如开机自启)→ 直接开窗看数据,不创建服务器,关窗不动后台
- probe=other(被其他程序占)→ 可操作提示,不开窗
- 空闲 → 起网关+看板再开窗,关窗停本次服务
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class FakeWebView:
    def __init__(self):
        self.create_window_calls = []
        self.started = False

    def create_window(self, *a, **kw):
        self.create_window_calls.append((a, kw))

    def start(self):
        self.started = True


class FakeServer:
    def __init__(self):
        self.shutdown_called = False

    def serve_forever(self):
        pass

    def shutdown(self):
        self.shutdown_called = True


class TestDesktop(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.mkdtemp(prefix="llms_home_")
        self._env = mock.patch.dict(
            os.environ,
            {"LLM_SANITIZER_HOME": self._home},
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        from llm_sanitizer import desktop

        self.desktop = desktop

    def _run(self, probes, fw):
        with mock.patch.object(self.desktop, "_HAS_WEBVIEW", True), \
             mock.patch.object(self.desktop, "webview", fw), \
             mock.patch.object(self.desktop.gateway, "probe_port",
                               side_effect=probes), \
             contextlib.redirect_stdout(io.StringIO()):
            return self.desktop.run()

    def test_missing_webview_returns_false(self):
        with mock.patch.object(self.desktop, "_HAS_WEBVIEW", False), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.desktop.run())

    def test_self_state_opens_window_without_starting_server(self):
        """后台已有服务:直接开窗,不创建/不关停服务。"""
        fw = FakeWebView()
        with mock.patch.object(self.desktop.gateway, "create_gateway_server") as m_gw, \
             mock.patch.object(self.desktop.dashboard, "create_dashboard_server") as m_db:
            ok = self._run(["self"], fw)
        self.assertTrue(ok)
        self.assertTrue(fw.started)
        self.assertEqual(len(fw.create_window_calls), 1)
        self.assertEqual(fw.create_window_calls[0][0][1],
                         f"http://127.0.0.1:{self.desktop.config.dashboard_port()}")
        m_gw.assert_not_called()  # 不重复起服务
        m_db.assert_not_called()

    def test_other_state_hints_and_no_window(self):
        fw = FakeWebView()
        buf = io.StringIO()
        with mock.patch.object(self.desktop, "_HAS_WEBVIEW", True), \
             mock.patch.object(self.desktop, "webview", fw), \
             mock.patch.object(self.desktop.gateway, "probe_port",
                               return_value="other"), \
             contextlib.redirect_stdout(buf):
            ok = self.desktop.run()
        self.assertFalse(ok)
        self.assertFalse(fw.started)
        self.assertIn("已被其他程序占用", buf.getvalue())

    def test_free_state_starts_servers_and_stops_on_close(self):
        """空闲:起服务开窗,关窗后停掉本次启动的服务。"""
        fw = FakeWebView()
        gs, ds = FakeServer(), FakeServer()
        with mock.patch.object(self.desktop.gateway, "create_gateway_server",
                               return_value=gs), \
             mock.patch.object(self.desktop.dashboard, "create_dashboard_server",
                               return_value=ds):
            ok = self._run([None, None], fw)
        self.assertTrue(ok)
        self.assertTrue(fw.started)
        self.assertTrue(gs.shutdown_called)
        self.assertTrue(ds.shutdown_called)

    def test_available(self):
        """available() 与模块实际依赖状态一致(沙箱未装 pywebview 时返回 False 是正确行为)。"""
        self.assertEqual(self.desktop.available(), self.desktop._HAS_WEBVIEW)


if __name__ == "__main__":
    unittest.main()
