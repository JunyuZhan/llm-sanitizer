"""端到端测试:mock 上游 + 真实网关/看板进程内启动,断言脱敏与还原。

运行(聚合 masker/CLI 单元测试一并执行):
    python3 tests/test_e2e.py
"""

import base64
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import mock_upstream  # noqa: E402
from llm_sanitizer import dashboard as db  # noqa: E402
from llm_sanitizer import gateway as gw  # noqa: E402
from llm_sanitizer import websocket as ws  # noqa: E402

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
    mock_factory = None  # 置为 MockWsUpstream 时走 ws:// 上游

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="llmsan-test-")
        # 通过环境变量配置,与真实运行路径一致(gateway/dashboard 共享 config)
        os.environ["LLM_SANITIZER_HOME"] = cls.home
        if cls.mock_factory:
            cls.mock = cls.mock_factory().start()
            scheme = "ws"
        else:
            cls.mock = mock_upstream.MockUpstream(mode=cls.mock_mode).start()
            scheme = "http"
        os.environ["LLM_SANITIZER_UPSTREAM"] = f"{scheme}://127.0.0.1:{cls.mock.port}"
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

    def last_raw(self):
        """最近一次 mock 收到的请求体(避免跨用例累积污染)。"""
        return self.mock.received[-1].decode("utf-8", "replace") if self.mock.received else ""

    def test_upstream_sees_placeholders_only(self):
        """AC-1:上游收到的内容不包含原文,只包含占位符。"""
        status, _ = _post(self.gport, "/v1/chat/completions", self._chat_payload())
        self.assertEqual(status, 200)
        raw = self.last_raw()
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

    def test_list_content_masked(self):
        """P1:敏感键下的字符串数组元素必须脱敏(content: ["原告张三"])。"""
        payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": ["原告张三 13912345678"]}]}
        status, _ = _post(self.gport, "/v1/chat/completions", payload)
        self.assertEqual(status, 200)
        raw = self.last_raw()
        self.assertNotIn("13912345678", raw)
        self.assertIn("[手机号_1]", raw)

    def test_tool_arguments_masked(self):
        """P1:多轮工具调用,请求侧 arguments 必须脱敏(响应侧已还原会明文回传)。"""
        payload = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "打电话"}],
            "tools": [{"type": "function", "function": {"name": "call", "parameters": {}}}],
        }
        # 模拟客户端回传上一轮的 arguments(还原后的明文)
        payload["messages"].append({
            "role": "assistant",
            "tool_calls": [{"type": "function", "id": "1",
                            "function": {"name": "call",
                                         "arguments": '{"to": "张三", "phone": "13912345678"}'}}],
        })
        payload["messages"].append({
            "role": "tool", "tool_call_id": "1",
            "content": "{\"to\": \"张三\", \"phone\": \"13912345678\"}",
        })
        status, _ = _post(self.gport, "/v1/chat/completions", payload)
        self.assertEqual(status, 200)
        raw = self.last_raw()
        self.assertNotIn("13912345678", raw)
        self.assertIn("[手机号_1]", raw)

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


class TestConsole(GatewayFixture):
    mock_mode = "chat_json"

    def test_agents_endpoint(self):
        """FR-11:引导检测接口返回 agents 列表(只读)。"""
        status, body = _get(self.dport, "/api/agents")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIsInstance(data["agents"], list)
        self.assertTrue(any(a["id"] == "codex" for a in data["agents"]))

    def test_agent_apply_requires_token(self):
        """FR-12:接入写接口无令牌返回 403。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
        conn.request("POST", "/api/agents/apply",
                     body=b'{"agent_id":"codex"}',
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        conn.close()
        self.assertEqual(resp.status, 403)

    def test_agent_apply_and_restore(self):
        """FR-12:一键接入写入配置(带 token),一键还原恢复原样。"""
        codex_dir = Path(self.home) / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        cfg = codex_dir / "config.toml"
        orig = '[model]\nname = "gpt-4o"\n'
        cfg.write_text(orig, encoding="utf-8")
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
            conn.request("POST", "/api/agents/apply",
                         body=json.dumps({"agent_id": "codex"}).encode(),
                         headers={"Content-Type": "application/json", "X-Local-Token": "local"})
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            self.assertEqual(resp.status, 200, body)
            self.assertTrue(json.loads(body)["ok"])
            text = cfg.read_text(encoding="utf-8")
            self.assertIn("[model_providers.llm-sanitizer]", text)
            self.assertIn(orig, text, "原配置必须保留")

            conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
            conn.request("POST", "/api/agents/restore",
                         body=json.dumps({"agent_id": "codex"}).encode(),
                         headers={"Content-Type": "application/json", "X-Local-Token": "local"})
            resp = conn.getresponse()
            conn.close()
            self.assertEqual(resp.status, 200)
            self.assertEqual(cfg.read_text(encoding="utf-8"), orig, "还原后应与原文一致")
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

    def test_settings_get(self):
        status, body = _get(self.dport, "/api/settings")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("upstream", data)
        self.assertIn("key_set", data)

    def test_settings_write_requires_token(self):
        """FR-8:写接口无本地令牌返回 403。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
        conn.request("POST", "/api/settings",
                     body=b'{"upstream":"http://127.0.0.1:1"}',
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 403)

    def test_settings_write_ok(self):
        """写接口带令牌成功,配置落盘。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
        conn.request("POST", "/api/settings",
                     body=json.dumps({"upstream": "http://127.0.0.1:9", "categories": ["姓名"]}).encode(),
                     headers={"Content-Type": "application/json", "X-Local-Token": "local"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertTrue(json.loads(body)["ok"])
        # 落盘且权限 600
        import os
        from llm_sanitizer import config as cfg
        p = cfg.settings_path()
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)

    def test_settings_write_cross_origin(self):
        """FR-8:跨域 Origin 写接口返回 403。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
        conn.request("POST", "/api/settings",
                     body=b'{"upstream":"http://127.0.0.1:9"}',
                     headers={"Content-Type": "application/json",
                              "X-Local-Token": "local",
                              "Origin": "http://evil.example.com"})
        resp = conn.getresponse()
        conn.close()
        self.assertEqual(resp.status, 403)

    def test_dashboard_host_validation(self):
        """P3:看板同样校验 Host 头(与网关一致)。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
        conn.request("GET", "/api/status", headers={"Host": "evil.example.com"})
        resp = conn.getresponse()
        conn.close()
        self.assertEqual(resp.status, 403)

    def test_wordlist_get(self):
        """v0.2:GET /api/wordlist 返回词表内容。"""
        status, body = _get(self.dport, "/api/wordlist")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("text", data)
        self.assertIn("count", data)

    def test_wordlist_write_requires_token(self):
        """v0.2:词表写接口无令牌返回 403。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
        conn.request("POST", "/api/wordlist",
                     body='{"text":"张三丰|姓名"}'.encode("utf-8"),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        conn.close()
        self.assertEqual(resp.status, 403)

    def test_wordlist_write_ok(self):
        """v0.2:词表写接口带令牌成功,落盘权限 600。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.dport, timeout=10)
        conn.request("POST", "/api/wordlist",
                     body=json.dumps({"text": "张三丰|姓名\n某某律所|公司名称\n"}).encode(),
                     headers={"Content-Type": "application/json", "X-Local-Token": "local"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertTrue(json.loads(body)["ok"])
        from llm_sanitizer import config as cfg
        p = cfg.wordlist_path()
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)
        self.assertIn("张三丰", p.read_text(encoding="utf-8"))


class TestAnthropicJSON(GatewayFixture):
    """协议适配(v0.2):Anthropic Messages API 非流式(Claude Code)。"""

    mock_mode = "anthropic_json"

    def _payload(self):
        return {
            "model": "claude-3-5-sonnet",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": SENSITIVE}],
            "system": "你是助理",
        }

    def last_raw(self):
        return self.mock.received[-1].decode("utf-8", "replace") if self.mock.received else ""

    def test_upstream_sees_placeholders_only(self):
        """AC-1(Anthropic):上游 messages content 只含占位符。"""
        status, _ = _post(self.gport, "/v1/messages", self._payload())
        self.assertEqual(status, 200)
        raw = self.last_raw()
        self.assertNotIn("张三", raw)
        self.assertNotIn("13912345678", raw)
        self.assertIn("[姓名_1]", raw)
        self.assertIn("[手机号_1]", raw)
        self.assertIn("[地址_1]", raw)

    def test_client_receives_restored_text_and_tool_input(self):
        """响应 text 与 tool_use.input(任意 JSON)均还原。"""
        _, body = _post(self.gport, "/v1/messages", self._payload())
        data = json.loads(body)
        text = data["content"][0]["text"]
        self.assertIn("张三", text)
        self.assertNotIn("[姓名_1]", text)
        tool_input = data["content"][1]["input"]
        self.assertEqual(tool_input["to"], "张三")
        self.assertEqual(tool_input["phone"], "13912345678")

    def test_anthropic_version_header_forwarded(self):
        """Anthropic 必填头 anthropic-version 必须透传上游。"""
        _post(self.gport, "/v1/messages", self._payload(),
              headers={"anthropic-version": "2023-06-01"})
        self.assertEqual(self.mock.received_headers[-1].get("anthropic-version"), "2023-06-01")

    def test_auth_headers(self):
        """密钥注入:Anthropic 用 x-api-key,其余用 Bearer。"""
        self.assertEqual(gw.auth_headers("https://api.anthropic.com/v1", "sk-x"),
                         {"x-api-key": "sk-x"})
        self.assertEqual(gw.auth_headers("https://api.openai.com/v1", "sk-y"),
                         {"Authorization": "Bearer sk-y"})
        self.assertEqual(gw.auth_headers("https://api.deepseek.com/v1", ""), {})


class TestAnthropicSSE(GatewayFixture):
    """协议适配:Anthropic SSE 流式(content_block_delta 分片还原)。"""

    mock_mode = "anthropic_sse"

    def test_anthropic_sse_restore(self):
        status, body = _post(self.gport, "/v1/messages", {
            "model": "claude-3-5-sonnet",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": SENSITIVE}],
        })
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("张三", text)
        self.assertIn("13912345678", text)
        self.assertNotIn("[姓名_1]", text)


class TestGeminiJSON(GatewayFixture):
    """协议适配(v0.2):Google Gemini generateContent 非流式。"""

    mock_mode = "gemini_json"

    def _payload(self):
        return {
            "contents": [{"role": "user", "parts": [{"text": SENSITIVE}]}],
            "systemInstruction": {"parts": [{"text": "你是助理"}]},
        }

    def test_upstream_sees_placeholders_only(self):
        """上游 contents.parts.text 只含占位符。"""
        status, _ = _post(self.gport, "/v1beta/models/gemini-pro:generateContent", self._payload())
        self.assertEqual(status, 200)
        raw = self.mock.bodies_text()
        self.assertNotIn("张三", raw)
        self.assertNotIn("13912345678", raw)
        self.assertIn("[姓名_1]", raw)
        self.assertIn("[手机号_1]", raw)

    def test_client_receives_restored_text(self):
        _, body = _post(self.gport, "/v1beta/models/gemini-pro:generateContent", self._payload())
        data = json.loads(body)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        self.assertIn("张三", text)
        self.assertNotIn("[姓名_1]", text)

    def test_forward_path_keeps_v1beta(self):
        """回归:/v1beta 前缀不能被误剥(Gemini 路径)。"""
        self.assertEqual(
            gw.forward_path("https://generativelanguage.googleapis.com",
                            "/v1beta/models/gemini-pro:generateContent"),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent")
        # /v1 前缀仍正常剥离(OpenAI)
        self.assertEqual(
            gw.forward_path("https://api.openai.com/v1", "/v1/chat/completions"),
            "https://api.openai.com/v1/chat/completions")


class TestGeminiSSE(GatewayFixture):
    """协议适配:Gemini streamGenerateContent SSE 分片还原。"""

    mock_mode = "gemini_sse"

    def test_gemini_sse_restore(self):
        status, body = _post(self.gport, "/v1beta/models/gemini-pro:streamGenerateContent?alt=sse", {
            "contents": [{"role": "user", "parts": [{"text": SENSITIVE}]}],
        })
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("张三", text)
        self.assertIn("13912345678", text)
        self.assertNotIn("[姓名_1]", text)


class TestWebSocket(GatewayFixture):
    """v0.2:WebSocket 透明代理(R1 缺口修复)。"""

    mock_factory = mock_upstream.MockWsUpstream

    def _ws_connect(self, path="/v1/realtime?model=gpt-4o"):
        """手写 WS 客户端:握手(掩码帧)并返回 (sock, reader)。"""
        s = socket.create_connection(("127.0.0.1", self.gport), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.gport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(req.encode("ascii"))
        reader = ws.WsReader(s)
        head = b""
        while b"\r\n\r\n" not in head:
            head += s.recv(4096)
        status = head.decode("latin-1").split("\r\n")[0]
        if "101" not in status:
            s.close()
            self.fail(f"ws handshake failed: {status}")
        return s, ws.WsReader(s, head.split(b"\r\n\r\n", 1)[1])

    def test_ws_upstream_sees_placeholders_only(self):
        """上游只见占位符;客户端收到还原原文。"""
        s, reader = self._ws_connect()
        try:
            ws.send_frame(s, ws.OP_TEXT, "原告张三 13912345678".encode("utf-8"), mask=True)
            opcode, payload = reader.recv_message()
            self.assertEqual(opcode, ws.OP_TEXT)
            text = payload.decode("utf-8")
            self.assertIn("张三", text)          # 回程还原
            self.assertIn("13912345678", text)
            self.assertNotIn("[姓名_1]", text)
            raw = self.mock.bodies_text()         # 上游只应见占位符
            self.assertNotIn("张三", raw)
            self.assertIn("[姓名_1]", raw)
            self.assertIn("[手机号_1]", raw)
        finally:
            try:
                ws.send_frame(s, ws.OP_CLOSE, b"\x03\xe8", mask=True)
                opcode, _ = reader.recv_message()
                self.assertEqual(opcode, ws.OP_CLOSE)
            except Exception:
                pass
            s.close()

    def test_ws_ping_pong(self):
        """控制帧透传:ping → 上游回 pong → 客户端收到。"""
        s, reader = self._ws_connect()
        try:
            ws.send_frame(s, ws.OP_PING, b"hi", mask=True)
            opcode, payload = reader.recv_message()
            self.assertEqual(opcode, ws.OP_PONG)
            self.assertEqual(payload, b"hi")
        finally:
            s.close()

    def test_ws_host_validation(self):
        """FR-8:伪造 Host 的 WS 握手返回 403。"""
        s = socket.create_connection(("127.0.0.1", self.gport), timeout=5)
        req = (
            "GET /v1/realtime HTTP/1.1\r\n"
            "Host: evil.example.com\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += s.recv(4096)
        status = resp.decode("latin-1").split("\r\n")[0]
        s.close()
        self.assertIn("403", status)

    def test_ws_dashboard_events(self):
        """WS 脱敏事件进入看板(仅占位符)。"""
        s, reader = self._ws_connect()
        try:
            ws.send_frame(s, ws.OP_TEXT, "原告张三 13912345678".encode("utf-8"), mask=True)
            reader.recv_message()  # 等回复,确保事件已落盘
        finally:
            s.close()
        status, body = _get(self.dport, "/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertGreaterEqual(data["total_masked"], 2)
        ev = json.dumps(data, ensure_ascii=False)
        self.assertIn("[姓名_1]", ev)
        self.assertNotIn("张三", ev)


if __name__ == "__main__":
    import test_cli
    import test_config_manager
    import test_masker

    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    suite.addTests(loader.loadTestsFromModule(test_masker))
    suite.addTests(loader.loadTestsFromModule(test_cli))
    suite.addTests(loader.loadTestsFromModule(test_config_manager))
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
