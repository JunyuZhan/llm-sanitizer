"""WebSocket 帧编解码与透明代理(纯标准库,零依赖)。

堵住 R1 缺口:部分 Agent(桌面版 Codex、OpenAI Realtime 等)走 WebSocket
通道,HTTP 网关无法拦截。本模块提供:

- 帧编解码:掩码、扩展长度、控制帧、分片累积
- 代理核心:客户端(服务器角色)↔ 上游(客户端角色)双向转发;
  文本消息在去程脱敏(mask_fn)、回程还原(restore_fn),
  二进制帧(如音频)与控制帧(ping/pong/close)透传。

设计契约:
- 上游目标支持 http(s):// 与 ws(s)://(https/wss 走 TLS)
- 发往上游的帧带掩码(客户端角色),发往客户端的不带(服务器角色)
- 文本消息整体按"所有字符串敏感"策略脱敏/还原,与工具参数一致,
  避免字段枚举漏网(对称还原)
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def accept_key(sec_websocket_key: str) -> str:
    """计算服务端握手响应的 Sec-WebSocket-Accept。"""
    return base64.b64encode(
        hashlib.sha1((sec_websocket_key + GUID).encode("ascii")).digest()
    ).decode("ascii")


class WsReader:
    """带缓冲的帧读取器(缓冲握手时可能多读到的字节)。"""

    def __init__(self, sock, initial=b""):
        self.sock = sock
        self.buf = initial

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv_frame(self):
        hdr = self._read(2)
        fin = bool(hdr[0] & 0x80)
        opcode = hdr[0] & 0x0F
        masked = bool(hdr[1] & 0x80)
        length = hdr[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        mask = self._read(4) if masked else None
        payload = self._read(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def recv_message(self):
        """累积数据分片为一条完整消息;控制帧单帧即返。返回 (opcode, payload)。"""
        opcode0 = None
        chunks = []
        while True:
            fin, opcode, payload = self.recv_frame()
            if opcode in (OP_CLOSE, OP_PING, OP_PONG):
                return opcode, payload
            if opcode0 is None:
                opcode0 = opcode
            chunks.append(payload)
            if fin:
                return opcode0, b"".join(chunks)


def send_frame(sock, opcode, payload=b"", mask=False):
    """发送一帧(fin=1)。mask:发往上游(客户端角色)必须掩码。"""
    b0 = 0x80 | opcode
    ln = len(payload)
    if ln < 126:
        hdr = bytes([b0, (0x80 if mask else 0) | ln])
    elif ln < 65536:
        hdr = bytes([b0, (0x80 if mask else 0) | 126]) + struct.pack(">H", ln)
    else:
        hdr = bytes([b0, (0x80 if mask else 0) | 127]) + struct.pack(">Q", ln)
    if mask:
        key = os.urandom(4)
        hdr += key
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    sock.sendall(hdr + payload)


def _tls_wrap(sock, scheme, hostname):
    if scheme in ("https", "wss"):
        ctx = ssl.create_default_context()
        return ctx.wrap_socket(sock, server_hostname=hostname)
    return sock


def connect_upstream(target, upstream_key=""):
    """连接 ws/wss/http/https 上游并发起 WS 握手。返回 (sock, WsReader)。

    目标为 http(s) 时按普通 TCP+TLS 直连(TLS 之后应用层仍是 WS 握手),
    即 https://api.openai.com/v1 这类 base + /realtime 路径可用。
    """
    parsed = urlsplit(target)
    scheme = parsed.scheme or "ws"
    hostname = parsed.hostname
    port = parsed.port or (443 if scheme in ("https", "wss") else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    sock = socket.create_connection((hostname, port), timeout=30)
    sock.settimeout(None)
    sock = _tls_wrap(sock, scheme, hostname)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
    )
    if upstream_key:
        req += f"Authorization: Bearer {upstream_key}\r\n"
    req += "\r\n"
    sock.sendall(req.encode("latin-1"))
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("upstream closed during ws handshake")
        head += chunk
    head_part, rest = head.split(b"\r\n\r\n", 1)
    status_line = head_part.decode("latin-1").split("\r\n")[0]
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or parts[1] != "101":
        raise ConnectionError(f"upstream ws handshake failed: {status_line}")
    return sock, WsReader(sock, rest)


def run_ws_proxy(client_sock, client_key, target, upstream_key,
                 mask_fn, restore_fn, log=lambda m: None):
    """透明 WebSocket 代理(阻塞至双向连接关闭)。

    client_sock: 已建立 TCP、尚未回 101 的客户端 socket
    client_key:  客户端握手请求的 Sec-WebSocket-Key
    target:      上游完整 URL(forward_path 结果)
    mask_fn/restore_fn: 文本消息的脱敏/还原回调(业务注入,含事件记录)

    顺序关键:先连接上游、成功后才回 101——上游不可达时连接仍处于
    HTTP 语义,调用方可正常返回 JSON 错误(避免 101 后写脏数据)。
    """
    up_sock, up_reader = connect_upstream(target, upstream_key)
    log(f"ws proxy connected to {target}")

    resp = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(client_key)}\r\n"
        "\r\n"
    )
    client_sock.sendall(resp.encode("latin-1"))
    client_reader = WsReader(client_sock)

    stop = threading.Event()

    def _pump(reader, writer_sock, to_upstream, transform):
        try:
            while not stop.is_set():
                opcode, payload = reader.recv_message()
                if opcode == OP_CLOSE:
                    try:
                        send_frame(writer_sock, OP_CLOSE, payload, to_upstream)
                    except OSError:
                        pass
                    stop.set()
                    break
                if opcode in (OP_PING, OP_PONG):
                    send_frame(writer_sock, opcode, payload, to_upstream)
                    continue
                if opcode == OP_TEXT:
                    try:
                        payload = transform(payload.decode("utf-8")).encode("utf-8")
                    except Exception as e:
                        log(f"ws transform error: {e}")
                try:
                    send_frame(writer_sock, opcode, payload, to_upstream)
                except OSError:
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            stop.set()

    t_c2u = threading.Thread(
        target=_pump, args=(client_reader, up_sock, True, mask_fn), daemon=True
    )
    t_u2c = threading.Thread(
        target=_pump, args=(up_reader, client_sock, False, restore_fn), daemon=True
    )
    t_c2u.start()
    t_u2c.start()
    t_c2u.join()
    t_u2c.join()
    for s in (client_sock, up_sock):
        try:
            s.close()
        except OSError:
            pass
