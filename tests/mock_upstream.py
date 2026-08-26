"""假上游:记录收到的请求体,回放 JSON 或 SSE 响应(测试用)。

用法:
    from tests.mock_upstream import MockUpstream
    mock = MockUpstream(mode="chat_json").start()
    url = f"http://127.0.0.1:{mock.port}"
    mock.last_body()      # 最近一次收到的请求体(dict)
    mock.received         # 全部收到的原始 body(bytes)
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm_sanitizer import websocket as ws


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        self.server.upstream.received.append(body)
        self.server.upstream.received_headers.append(dict(self.headers))
        self.server.upstream._respond(self)

    def do_GET(self):
        self.server.upstream._respond(self)


class MockUpstream:
    """mode: chat_json / chat_sse / responses_json / responses_sse /
    anthropic_json / anthropic_sse。"""

    def __init__(self, mode="chat_json", chunk=3):
        self.mode = mode
        self.chunk = chunk          # SSE 每片字符数(故意切碎 token)
        self.received = []
        self.received_headers = []
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
        elif self.mode == "anthropic_json":
            self._json(handler, {
                "id": "msg_01",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "好的,[姓名_1] 的号码是 [手机号_1]"},
                    {"type": "tool_use", "id": "t1", "name": "lookup",
                     "input": {"to": "[姓名_1]", "phone": "[手机号_1]"}},
                ],
                "stop_reason": "end_turn",
            })
        elif self.mode == "anthropic_sse":
            self._sse_anthropic(handler, "好的,[姓名_1] 的号码是 [手机号_1]")
        elif self.mode == "gemini_json":
            self._json(handler, {
                "candidates": [{
                    "content": {"role": "model",
                                "parts": [{"text": "好的,[姓名_1] 的号码是 [手机号_1]"}]},
                    "finishReason": "STOP",
                }]
            })
        elif self.mode == "gemini_sse":
            self._sse_gemini(handler, "好的,[姓名_1] 的号码是 [手机号_1]")

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

    def _sse_anthropic(self, handler, text):
        """Anthropic Messages SSE:content_block_delta(text_delta) 分片 + message_stop。"""
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        for i in range(0, len(text), self.chunk):
            piece = text[i : i + self.chunk]
            ev = json.dumps({"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": piece}},
                            ensure_ascii=False)
            handler.wfile.write(f"event: content_block_delta\ndata: {ev}\n\n".encode())
            handler.wfile.flush()
        ev = json.dumps({"type": "message_stop"}, ensure_ascii=False)
        handler.wfile.write(f"event: message_stop\ndata: {ev}\n\n".encode())
        handler.wfile.flush()
        handler.close_connection = True

    def _sse_gemini(self, handler, text):
        """Gemini streamGenerateContent SSE:data 行是 candidates JSON,分片发送。"""
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        for i in range(0, len(text), self.chunk):
            piece = text[i : i + self.chunk]
            ev = json.dumps({"candidates": [{"content": {"parts": [{"text": piece}]}}]},
                            ensure_ascii=False)
            handler.wfile.write(f"data: {ev}\n\n".encode())
            handler.wfile.flush()
        ev = json.dumps({"candidates": [{"content": {"parts": [{"text": ""}]},
                                         "finishReason": "STOP"}]}, ensure_ascii=False)
        handler.wfile.write(f"data: {ev}\n\n".encode())
        handler.wfile.flush()
        handler.close_connection = True


if __name__ == "__main__":
    mock = MockUpstream(mode="chat_json").start()
    print(f"mock upstream at http://127.0.0.1:{mock.port} (mode={mock.mode})")
    threading.Event().wait()


class MockWsUpstream:
    """WebSocket 假上游:接收文本消息,回一条把占位符组织进回复的消息。

    用于验证网关 WS 代理:上游只应看到占位符,回复中的占位符
    在回程被还原,客户端最终收到原文。
    """

    def __init__(self):
        self.received = []  # 收到的完整消息(bytes)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        try:
            self._sock.close()
        except OSError:
            pass

    def bodies_text(self):
        return b"".join(self.received).decode("utf-8", "replace")

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        head = b""
        while b"\r\n\r\n" not in head:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            head += chunk
        head_part, rest = head.split(b"\r\n\r\n", 1)
        key = None
        for line in head_part.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        if not key:
            return
        try:
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {ws.accept_key(key)}\r\n\r\n"
                ).encode("latin-1")
            )
        except OSError:
            return
        r2 = ws.WsReader(conn, rest)
        try:
            while True:
                opcode, payload = r2.recv_message()
                if opcode == ws.OP_CLOSE:
                    ws.send_frame(conn, ws.OP_CLOSE, payload)
                    return
                if opcode == ws.OP_PING:  # 规范要求回 pong
                    ws.send_frame(conn, ws.OP_PONG, payload)
                    continue
                if opcode != ws.OP_TEXT:
                    continue
                self.received.append(payload)
                reply = f"好的,已收到 {payload.decode('utf-8', 'replace')}"
                ws.send_frame(conn, ws.OP_TEXT, reply.encode("utf-8"))
        except (ConnectionError, OSError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass
