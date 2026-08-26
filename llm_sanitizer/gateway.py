"""本地隐私网关：请求脱敏 → 转发上游 → 响应还原。

支持 OpenAI Responses API 与 Chat Completions，含 SSE 流式。
"""

import json
import os
import sys
import threading
import time
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import config
from .events import EventStore
from .masker import Masker, mask_text, restore_text

# 请求侧：这些字段里的文本会被脱敏
MASK_KEYS = {"content", "text", "input", "instructions", "prompt", "system", "description"}
# 响应侧：这些字段里的文本会被还原（delta 字段单独走流式缓冲）
RESTORE_KEYS = {"content", "text", "summary"}
SSE = "text/event-stream"


class GatewayState:
    def __init__(self, upstream, upstream_key, map_path, events_path):
        self.masker = Masker()
        self.lock = threading.Lock()
        self.map_path = map_path
        self.events = EventStore(events_path)
        self.upstream = upstream
        self.upstream_key = upstream_key
        self.verbose = False
        self.total_findings = 0


state = None


def init_state(upstream=None, upstream_key=None, map_path=None, events_path=None):
    global state
    st = GatewayState(
        upstream or config.upstream(),
        upstream_key if upstream_key is not None else config.upstream_key(),
        str(map_path or config.map_path()),
        str(events_path or config.events_path()),
    )
    st.masker.load_mapping(_load_json(st.map_path))
    state = st  # 修复:必须赋给全局,否则请求处理时 state 为 None
    return st


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def token_category(token):
    """从 [姓名_1] 提取类别 '姓名'。"""
    if token.startswith("[") and "_" in token and token.endswith("]"):
        return token[1 : token.rfind("_")]
    return "?"


# ---------------------------------------------------------------------------
# 请求脱敏 / 响应还原
# ---------------------------------------------------------------------------
def mask_json(obj, keys):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and k in keys:
                with state.lock:
                    masked, _ = mask_text(v, state.masker)
                out[k] = masked
            else:
                out[k] = mask_json(v, keys)
        return out
    if isinstance(obj, list):
        return [mask_json(v, keys) for v in obj]
    return obj


def restore_json(obj):
    """递归还原 content/text/summary 字段;工具调用参数(arguments JSON 字符串)
    单独处理(D3 修复)。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and k in RESTORE_KEYS:
                out[k] = restore_text(v, state.masker.mapping)
            elif k == "arguments" and isinstance(v, str):
                out[k] = _restore_json_string(v)
            else:
                out[k] = restore_json(v)
        return out
    if isinstance(obj, list):
        return [restore_json(v) for v in obj]
    return obj


def _restore_json_string(s):
    """把 JSON 字符串中的占位符还原(如 tool_calls[].function.arguments)。"""
    try:
        obj = json.loads(s)
    except Exception:
        return s
    return json.dumps(restore_json(obj), ensure_ascii=False)


class StreamRestorer:
    """流式还原：SSE 分片可能把 token 切成两半（如 "[姓名" / "_1]"），
    保留“可能是 token 前缀”的尾部，等下一个分片凑齐后再还原。"""

    def __init__(self):
        self.pending = ""

    def reset(self):
        self.pending = ""

    def feed(self, chunk):
        s = self.pending + chunk
        tokens = sorted(state.masker.mapping, key=len, reverse=True)
        out = []
        i = 0
        while i < len(s):
            hit = None
            for t in tokens:
                if s.startswith(t, i):
                    hit = t
                    break
            if hit:
                out.append(state.masker.mapping[hit])
                i += len(hit)
            else:
                out.append(s[i])
                i += 1
        resolved = "".join(out)
        keep = None
        for k in range(len(resolved)):
            suffix = resolved[k:]
            if suffix and any(t.startswith(suffix) for t in tokens):
                keep = k
                break
        if keep is None:
            self.pending = ""
            return resolved
        self.pending = resolved[keep:]
        return resolved[:keep]

    def flush(self):
        out = self.pending
        self.pending = ""
        return out


# ---------------------------------------------------------------------------
# 转发
# ---------------------------------------------------------------------------
def forward_path(base, req_path):
    """客户端路径统一去 /v1 前缀，再拼到上游 base。"""
    base_clean = base.rstrip("/")
    query = ""
    if "?" in req_path:
        req_path, query = req_path.split("?", 1)
    if req_path.startswith("/v1"):
        req_path = req_path[len("/v1"):] or "/"
    return base_clean + req_path + ("?" + query if query else "")


def open_upstream():
    parsed = urlsplit(state.upstream)
    scheme = parsed.scheme or "https"
    port = parsed.port or (443 if scheme == "https" else 80)
    conn_cls = HTTPSConnection if scheme == "https" else HTTPConnection
    return conn_cls(parsed.hostname, port, timeout=900)


def forward(conn, method, path, headers, body):
    out_headers = {"Accept-Encoding": "identity", "Content-Length": str(len(body))}
    for k, v in headers.items():
        lk = k.lower()
        if lk in ("authorization", "content-type", "accept", "user-agent") or lk.startswith("x-"):
            out_headers[k] = v
    if state.upstream_key:
        out_headers["Authorization"] = "Bearer " + state.upstream_key
    conn.request(method, forward_path(state.upstream, path), body=body, headers=out_headers)
    return conn.getresponse()


# ---------------------------------------------------------------------------
# HTTP 处理
# ---------------------------------------------------------------------------
class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LLMSanitizer/0.1"

    def log_message(self, fmt, *args):
        if state and state.verbose:
            sys.stderr.write("[gateway] " + fmt % args + "\n")

    def do_GET(self):
        self._route(b"")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self._route(body)

    def _route(self, body):
        # FR-8:校验 Host / Origin,防 DNS rebinding 与跨站请求
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host not in ("127.0.0.1", "localhost"):
            self._json_error(403, "forbidden host")
            return
        origin = self.headers.get("Origin") or ""
        if origin:
            o_host = origin.split("//")[-1].split("/")[0].split(":")[0].lower()
            if o_host not in ("127.0.0.1", "localhost"):
                self._json_error(403, "forbidden origin")
                return
        try:
            payload = body
            if body and body.lstrip().startswith(b"{"):
                obj = json.loads(body)
                with state.lock:
                    before = set(state.masker.mapping)
                masked_obj = mask_json(obj, MASK_KEYS)
                payload = json.dumps(masked_obj, ensure_ascii=False).encode("utf-8")
                with state.lock:  # D4 修复:map.json 写入持锁
                    new_tokens = set(state.masker.mapping) - before
                    state.total_findings += len(new_tokens)
                    _save_json(state.map_path, state.masker.mapping)
                for token in new_tokens:
                    state.events.add("mask", category=token_category(token), token=token)
                state.events.add(
                    "request",
                    method=self.command,
                    path=self.path,
                    new_findings=len(new_tokens),
                    total=len(state.masker.mapping),
                )
                sys.stderr.write(
                    f"[gateway] {time.strftime('%H:%M:%S')} {self.command} {self.path} "
                    f"新增脱敏 {len(new_tokens)} 项（累计 {state.total_findings} 项）\n"
                )
            self._forward(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._json_error(400, f"bad request json: {e}")
        except Exception as e:
            self._json_error(502, f"gateway error: {e}")

    def _forward(self, body):
        conn = open_upstream()
        try:
            resp = forward(conn, self.command, self.path, dict(self.headers.items()), body)
        except Exception as e:
            conn.close()  # D6 修复:异常路径释放连接
            self._json_error(502, f"upstream unreachable: {e}")
            return
        ctype = resp.getheader("Content-Type", "") or ""
        self.send_response(resp.status)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if SSE in ctype:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._stream_sse(resp)
        else:
            raw = resp.read()
            out = self._restore_body(raw)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        conn.close()

    def _restore_body(self, raw):
        try:
            obj = json.loads(raw)
            return json.dumps(restore_json(obj), ensure_ascii=False).encode("utf-8")
        except Exception:
            return raw

    def _write_chunk(self, data):
        if not data:
            return
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")

    def _stream_sse(self, resp):
        restorer = StreamRestorer()
        event_lines = []
        event_names = []
        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                if line in (b"\n", b"\r\n"):
                    if event_lines:
                        self._emit_event(event_names, event_lines, restorer)
                    event_lines = []
                    event_names = []
                    continue
                if line.startswith(b"event:"):
                    event_names.append(line[len(b"event:"):].strip().decode())
                if line.startswith(b"data:"):
                    event_lines.append(line[len(b"data:"):].strip())
                else:
                    self._write_chunk(line)
            if event_lines:
                self._emit_event(event_names, event_lines, restorer)
            tail = restorer.flush()
            if tail:
                self._write_chunk(tail.encode("utf-8"))
        finally:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    def _emit_event(self, names, data_lines, restorer):
        data = b"\n".join(data_lines)
        if data.strip() == b"[DONE]":
            self._write_chunk(b"data: [DONE]\n\n")
            return
        try:
            obj = json.loads(data)
            self._transform_event(obj, restorer)
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        except Exception:
            pass
        block = b"".join(b"event: " + n.encode("utf-8") + b"\n" for n in names)
        block += b"data: " + data + b"\n\n"
        self._write_chunk(block)

    def _transform_event(self, obj, restorer):
        if not isinstance(obj, dict):
            return
        typ = obj.get("type")
        if typ == "response.output_text.delta" and isinstance(obj.get("delta"), str):
            obj["delta"] = restorer.feed(obj["delta"])
        elif typ == "response.output_text.done" and isinstance(obj.get("text"), str):
            obj["text"] = restore_text(obj["text"], state.masker.mapping)
            restorer.reset()
        elif typ == "response.reasoning_text.delta" and isinstance(obj.get("delta"), str):
            obj["delta"] = restorer.feed(obj["delta"])
        elif typ == "response.reasoning_text.done" and isinstance(obj.get("text"), str):
            obj["text"] = restore_text(obj["text"], state.masker.mapping)
            restorer.reset()
        elif typ == "response.reasoning_summary.delta" and isinstance(obj.get("summary"), str):
            obj["summary"] = restorer.feed(obj["summary"])
        elif typ == "response.reasoning_summary.done" and isinstance(obj.get("summary"), str):
            obj["summary"] = restore_text(obj["summary"], state.masker.mapping)
            restorer.reset()
        elif typ == "response.completed":
            if isinstance(obj.get("response"), dict):
                obj["response"] = restore_json(obj["response"])
            restorer.reset()
        elif typ in ("response.content_part.delta",) and isinstance(obj.get("delta"), str):
            obj["delta"] = restorer.feed(obj["delta"])
        elif typ == "response.function_call_arguments.done" and isinstance(obj.get("arguments"), str):
            obj["arguments"] = _restore_json_string(obj["arguments"])
        elif "choices" in obj:
            for ch in obj.get("choices") or []:
                if not isinstance(ch, dict):
                    continue
                delta = ch.get("delta")
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    delta["content"] = restorer.feed(delta["content"])
                if isinstance(delta, dict) and isinstance(delta.get("tool_calls"), list):
                    for tc in delta["tool_calls"]:
                        if isinstance(tc, dict) and isinstance(tc.get("function"), dict):
                            fn = tc["function"]
                            if isinstance(fn.get("arguments"), str):
                                fn["arguments"] = _restore_json_string(fn["arguments"])
                msg = ch.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    msg["content"] = restore_text(msg["content"], state.masker.mapping)
                    restorer.reset()
                if isinstance(msg, dict) and isinstance(msg.get("tool_calls"), list):
                    for tc in msg["tool_calls"]:
                        if isinstance(tc, dict) and isinstance(tc.get("function"), dict):
                            fn = tc["function"]
                            if isinstance(fn.get("arguments"), str):
                                fn["arguments"] = _restore_json_string(fn["arguments"])
        else:
            obj.update(restore_json(obj))  # D2 修复:使用还原后的返回值

    def _json_error(self, status, message):
        body = json.dumps({"error": {"message": message}}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_gateway_server(port=None):
    return ThreadingHTTPServer(
        (config.host(), port if port is not None else config.gateway_port()), GatewayHandler
    )
