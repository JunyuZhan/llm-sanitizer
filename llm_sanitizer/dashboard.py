"""实时看板：浏览器访问 http://127.0.0.1:8791，每 2 秒轮询事件文件。"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import config
from .events import tail_events


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM Sanitizer · 脱敏看板</title>
<style>
  body { font-family: -apple-system, "PingFang SC", sans-serif; margin: 0; background: #f6f7f9; color: #1c2333; }
  header { background: #101828; color: #fff; padding: 18px 28px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; margin: 0; }
  #live { font-size: 12px; background: #16a34a; padding: 3px 10px; border-radius: 20px; }
  #live.off { background: #dc2626; }
  main { max-width: 980px; margin: 24px auto; padding: 0 16px; }
  .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 24px; }
  .card { background: #fff; border-radius: 12px; padding: 18px; box-shadow: 0 1px 3px rgba(16,24,40,.08); }
  .num { font-size: 30px; font-weight: 700; }
  .label { color: #667085; font-size: 13px; margin-top: 4px; }
  h2 { font-size: 15px; margin: 22px 0 10px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(16,24,40,.08); }
  th, td { text-align: left; padding: 9px 14px; font-size: 13px; border-bottom: 1px solid #eef0f3; }
  th { background: #f9fafb; color: #475467; font-weight: 600; }
  .tag { display: inline-block; background: #eef2ff; color: #4338ca; border-radius: 6px; padding: 1px 8px; font-size: 12px; }
  .mono { font-family: ui-monospace, Menlo, monospace; }
  .bar { background: #eef0f3; border-radius: 6px; height: 10px; overflow: hidden; }
  .bar i { display: block; height: 100%; background: #4f46e5; }
</style>
</head>
<body>
<header><h1>LLM Sanitizer · 脱敏看板</h1><span id="live">运行中</span></header>
<main>
  <div class="cards">
    <div class="card"><div class="num" id="total">0</div><div class="label">累计脱敏（占位符）</div></div>
    <div class="card"><div class="num" id="requests">0</div><div class="label">请求数</div></div>
    <div class="card"><div class="num" id="cats">0</div><div class="label">敏感类别</div></div>
  </div>
  <h2>按类别分布</h2><div id="bars"></div>
  <h2>最近脱敏事件（不含明文）</h2>
  <table><thead><tr><th>时间</th><th>类别</th><th>占位符</th><th>请求</th></tr></thead>
  <tbody id="events"></tbody></table>
  <h2>最近请求</h2>
  <table><thead><tr><th>时间</th><th>方法</th><th>路径</th><th>新增脱敏</th></tr></thead>
  <tbody id="reqs"></tbody></table>
</main>
<script>
async function refresh() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('live').className = '';
    document.getElementById('live').textContent = '运行中';
    document.getElementById('total').textContent = d.total_masked;
    document.getElementById('requests').textContent = d.requests;
    const cats = Object.keys(d.by_category).length;
    document.getElementById('cats').textContent = cats;
    const bars = document.getElementById('bars');
    const max = Math.max(1, ...Object.values(d.by_category));
    bars.innerHTML = Object.entries(d.by_category).map(([k, v]) =>
      '<div style="margin-bottom:8px">' + k + ' <span style="float:right">' + v + '</span>' +
      '<div class="bar"><i style="width:' + (v / max * 100) + '%"></i></div></div>').join('');
    document.getElementById('events').innerHTML = d.events.map(e =>
      '<tr><td>' + e.ts + '</td><td><span class="tag">' + e.category + '</span></td>' +
      '<td class="mono">' + e.token + '</td><td>' + (e.path || '') + '</td></tr>').join('');
    document.getElementById('reqs').innerHTML = d.reqs.map(e =>
      '<tr><td>' + e.ts + '</td><td>' + e.method + '</td><td class="mono">' + e.path + '</td>' +
      '<td>' + e.new_findings + '</td></tr>').join('');
  } catch (e) {
    document.getElementById('live').className = 'off';
    document.getElementById('live').textContent = '看板服务异常';
  }
}
setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LLMSanitizerDashboard/0.1"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        # FR-8:拒绝跨域 Origin(防 DNS rebinding 页面读取看板数据)
        origin = self.headers.get("Origin") or ""
        if origin:
            o_host = origin.split("//")[-1].split("/")[0].split(":")[0].lower()
            if o_host not in ("127.0.0.1", "localhost"):
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            ctype = "text/html; charset=utf-8"
        elif path == "/api/status":
            events = tail_events(str(config.events_path()), limit=300)
            masked = [e for e in events if e.get("kind") == "mask"]
            reqs = [e for e in events if e.get("kind") == "request"]
            by_cat = {}
            for e in masked:
                c = e.get("category", "?")
                by_cat[c] = by_cat.get(c, 0) + 1
            body = json.dumps(
                {
                    "total_masked": len(masked),
                    "requests": len(reqs),
                    "by_category": by_cat,
                    "events": list(reversed(masked[-20:])),
                    "reqs": list(reversed(reqs[-15:])),
                    "updated": time.strftime("%H:%M:%S"),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            body = b"not found"
            ctype = "text/plain"
            self.send_response(404)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_dashboard_server(port=None):
    return ThreadingHTTPServer(
        (config.host(), port if port is not None else config.dashboard_port()), DashboardHandler
    )
