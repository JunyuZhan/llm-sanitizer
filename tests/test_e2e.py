"""端到端测试:mock 上游 + 真实网关/看板进程内启动,断言脱敏与还原。

运行(聚合 masker/CLI 单元测试一并执行):
    python3 tests/test_e2e.py
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import mock_upstream  # noqa: E402
from llm_sanitizer import dashboard as db  # noqa: E402
from llm_sanitizer import gateway as gw  # noqa: E402

SENSITIVE = "原告张三 电话13912345678 住址:北京市朝阳区建国路88号"


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _post(port, path, payload, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    conn.request("POST", path, body=json.dumps(payload, ensure_ascii=False).encode(), headers=h)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


class GatewayFixture(unittest.TestCase):
    """每个测试类独立的 mock + 网关 + 看板。"""

    mock_mode = "chat_json"

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="llmsan-test-")
        # 通过环境变量配置,与真实运行路径一致(gateway/dashboard 共享 config)
        os.environ["LLM_SANITIZER_HOME"] = cls.home
        cls.mock = mock_upstream.MockUpstream(mode=cls.mock_mode).start()
        os.environ["LLM_SANITIZER_UPSTREAM"] = f"http://127.0.0.1:{cls.mock.port}"
        gw.init_state()
        cls.gs = gw.create_gateway_server(port=0)
        cls.gport = cls.gs.server_address[1]
        threading.Thread(target=cls.gs.serve_forever, daemon=True).start()
        cls.ds = db.create_dashboard_server(port=0)
        cls.dport = cls.ds.server_address[1]
        threading.Thread(target=cls.ds.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.gs.shutdown()
        cls.ds.shutdown()
        cls.mock.stop()

    def _chat_payload(self):
        return {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": SENSITIVE}],
        }


class TestChatJSON(GatewayFixture):
    mock_mode = "chat_json"

    def test_upstream_sees_placeholders_only(self):
        """AC-1:上游收到的内容不包含原文,只包含占位符。"""
        status, _ = _post(self.gport, "/v1/chat/completions", self._chat_payload())
        self.assertEqual(status, 200)
        raw = self.mock.bodies_text()
        self.assertNotIn("张三", raw)
        self.assertNotIn("13912345678", raw)
        self.assertIn("[姓名_1]", raw)
        self.assertIn("[手机号_1]", raw)
        self.assertIn("[地址_1]", raw)

    def test_client_receives_restored_text(self):
        """AC-2:客户端收到的响应为还原后的原文。"""
        _, body = _post(self.gport, "/v1/chat/completions", self._chat_payload())
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        self.assertIn("张三", content)
        self.assertIn("13912345678", content)
        self.assertNotIn("[姓名_1]", content)

    def test_dashboard_events(self):
        """AC-3:脱敏事件出现在看板(仅占位符,无明文)。"""
        _post(self.gport, "/v1/chat/completions", self._chat_payload())
        status, body = _get(self.dport, "/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertGreaterEqual(data["total_masked"], 3)
        ev = json.dumps(data, ensure_ascii=False)
        self.assertIn("[姓名_1]", ev)
        self.assertNotIn("张三", ev)

    def test_host_validation(self):
        """FR-8:伪造 Host 头返回 403(DNS rebinding 缓解)。"""
        status, _ = _post(self.gport, "/v1/chat/completions", self._chat_payload(),
                          headers={"Host": "evil.example.com"})
        self.assertEqual(status, 403)

    def test_origin_validation(self):
        """FR-8:跨域 Origin 返回 403。"""
        status, _ = _post(self.gport, "/v1/chat/completions", self._chat_payload(),
                          headers={"Origin": "http://evil.example.com"})
        self.assertEqual(status, 403)


class TestChatSSE(GatewayFixture):
    mock_mode = "chat_sse"

    def test_sse_streaming_restore(self):
        """AC-4:SSE 流式响应,分片切碎 token 也能还原。"""
        status, body = _post(self.gport, "/v1/chat/completions", self._chat_payload())
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("张三", text)
        self.assertIn("13912345678", text)
        self.assertNotIn("[姓名_1]", text)
        self.assertIn("[DONE]", text)

    def test_upstream_placeholders(self):
        raw = self.mock.bodies_text()
        self.assertNotIn("张三", raw)
        self.assertIn("[姓名_1]", raw)


class TestResponsesJSON(GatewayFixture):
    mock_mode = "responses_json"

    def test_responses_restore(self):
        payload = {"model": "gpt-4o", "input": SENSITIVE}
        status, body = _post(self.gport, "/v1/responses", payload)
        self.assertEqual(status, 200)
        data = json.loads(body)
        text = json.dumps(data, ensure_ascii=False)
        self.assertIn("张三", text)
        self.assertNotIn("[姓名_1]", text)
        raw = self.mock.bodies_text()
        self.assertNotIn("张三", raw)


if __name__ == "__main__":
    import test_cli
    import test_masker

    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    suite.addTests(loader.loadTestsFromModule(test_masker))
    suite.addTests(loader.loadTestsFromModule(test_cli))
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
