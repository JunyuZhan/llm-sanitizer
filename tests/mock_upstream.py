"""假上游:记录收到的请求体,回放 JSON 或 SSE 响应(测试用)。

用法:
    from tests.mock_upstream import MockUpstream
    mock = MockUpstream(mode="chat_json").start()
    url = f"http://127.0.0.1:{mock.port}"
    mock.last_body()      # 最近一次收到的请求体(dict)
    mock.received         # 全部收到的原始 body(bytes)
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        self.server.upstream.received.append(body)
        self.server.upstream._respond(self)

    def do_GET(self):
        self.server.upstream._respond(self)


class MockUpstream:
    """mode: chat_json / chat_sse / responses_json / responses_sse。"""

    def __init__(self, mode="chat_json", chunk=3):
        self.mode = mode
        self.chunk = chunk          # SSE 每片字符数(故意切碎 token)
        self.received = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.upstream = self
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def last_body(self):
        if not self.received:
            return {}
        try:
            return json.loads(self.received[-1].decode())
        except Exception:
            return {}

    def bodies_text(self):
        """所有收到的请求体拼接为文本(断言无明文用)。"""
        return b"".join(self.received).decode("utf-8", "replace")

    def _respond(self, handler):
        if self.mode == "chat_json":
            self._json(handler, {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "好的,[姓名_1] 的号码是 [手机号_1],住址是 [地址_1]",
                    }
                }]
            })
        elif self.mode == "chat_sse":
            self._sse(handler, "好的,[姓名_1] 的号码是 [手机号_1],住址是 [地址_1]")
        elif self.mode == "responses_json":
            self._json(handler, {
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "好的,[姓名_1]"}],
                }]
            })
        elif self.mode == "responses_sse":
            self._sse(handler, "好的,[姓名_1] 的号码是 [手机号_1]")

    def _json(self, handler, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def _sse(self, handler, text):
        """逐片发送 Chat Completions SSE;写完关闭连接(网关读到 EOF 收尾)。"""
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        for i in range(0, len(text), self.chunk):
            piece = text[i : i + self.chunk]
            ev = json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False)
            handler.wfile.write(f"data: {ev}\n\n".encode())
            handler.wfile.flush()
        handler.wfile.write(b"data: [DONE]\n\n")
        handler.wfile.flush()
        handler.close_connection = True


if __name__ == "__main__":
    mock = MockUpstream(mode="chat_json").start()
    print(f"mock upstream at http://127.0.0.1:{mock.port} (mode={mock.mode})")
    threading.Event().wait()
