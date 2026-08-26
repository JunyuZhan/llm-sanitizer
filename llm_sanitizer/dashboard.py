"""实时看板 → 控制台:统计、接入引导(FR-11)、设置(FR-13/FR-15)。

- GET  /                单页控制台(原生 JS,2 秒轮询统计)
- GET  /api/status      统计(持久化 per-category 计数器 + 最近事件)
- GET  /api/agents      本机 Agent 检测(只读,FR-11)
- GET  /api/settings    读取设置(不含密钥明文)
- POST /api/settings    保存设置(Origin 白名单 + X-Local-Token,FR-8)
"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import config, config_manager
from .events import tail_events

ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost")


def _origin_ok(headers) -> bool:
    origin = headers.get("Origin") or ""
    if not origin:
        return True
    host = origin.split("//")[-1].split("/")[0].split(":")[0].lower()
    return host in ALLOWED_ORIGIN_HOSTS


def _host_ok(headers) -> bool:
    """校验 Host 头(仅回环),与网关一致,防 DNS rebinding。"""
    host = (headers.get("Host") or "").split(":")[0].lower()
    return host in ALLOWED_ORIGIN_HOSTS


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM Sanitizer · 控制台</title>
<style>
  body { font-family: -apple-system, "PingFang SC", sans-serif; margin: 0; background: #f6f7f9; color: #1c2333; }
  header { background: #101828; color: #fff; padding: 16px 28px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 17px; margin: 0; }
  #live { font-size: 12px; background: #16a34a; padding: 3px 10px; border-radius: 20px; }
  #live.off { background: #dc2626; }
  nav { display: flex; gap: 18px; margin-left: auto; font-size: 13px; }
  nav a { color: #cbd5e1; text-decoration: none; }
  nav a:hover { color: #fff; }
  main { max-width: 1040px; margin: 22px auto; padding: 0 16px; }
  .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 20px; }
  .card { background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(16,24,40,.08); }
  .num { font-size: 28px; font-weight: 700; }
  .label { color: #667085; font-size: 13px; margin-top: 4px; }
  h2 { font-size: 15px; margin: 22px 0 10px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(16,24,40,.08); }
  th, td { text-align: left; padding: 8px 14px; font-size: 13px; border-bottom: 1px solid #eef0f3; }
  th { background: #f9fafb; color: #475467; font-weight: 600; }
  .tag { display: inline-block; background: #eef2ff; color: #4338ca; border-radius: 6px; padding: 1px 8px; font-size: 12px; }
  .mono { font-family: ui-monospace, Menlo, monospace; }
  .bar { background: #eef0f3; border-radius: 6px; height: 10px; overflow: hidden; }
  .bar i { display: block; height: 100%; background: #4f46e5; }
  .panel { background: #fff; border-radius: 12px; padding: 18px 20px; box-shadow: 0 1px 3px rgba(16,24,40,.08); margin-bottom: 16px; }
  .panel h3 { margin: 0 0 12px; font-size: 14px; }
  form label { display: block; font-size: 13px; color: #475467; margin: 10px 0 4px; }
  input[type=text], input[type=password] { width: 100%; max-width: 460px; padding: 8px 12px; border: 1px solid #d0d5dd; border-radius: 8px; font-size: 13px; box-sizing: border-box; }
  .chk { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; margin: 6px 14px 0 0; }
  .btn { padding: 8px 18px; border: 1px solid #d0d5dd; border-radius: 8px; background: #fff; font-size: 13px; cursor: pointer; }
  .btn-p { background: #4f46e5; color: #fff; border-color: #4f46e5; }
  .btn-p:hover { background: #3730a3; }
  .preset { margin: 10px 0 4px; }
  .preset button { font-size: 12px; padding: 4px 12px; }
  .ok { color: #16a34a; font-size: 13px; margin-left: 10px; }
  .warn { background: #fef3c7; color: #92400e; border-radius: 8px; padding: 9px 14px; font-size: 12.5px; margin-top: 10px; }
  pre { background: #0f172a; color: #e2e8f0; border-radius: 10px; padding: 12px 16px; font-size: 12.5px; overflow-x: auto; line-height: 1.5; }
  .agent { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border: 1px solid #eef0f3; border-radius: 8px; margin-bottom: 8px; font-size: 13px; }
  .det { font-size: 12px; }
  .det.y { color: #16a34a; }
  .det.n { color: #667085; }
</style>
</head>
<body>
<header>
  <h1>LLM Sanitizer · 控制台</h1><span id="live">运行中</span>
  <nav>
    <a href="#guide">接入引导</a>
    <a href="#settings">设置</a>
    <a href="#events">事件</a>
  </nav>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="num" id="total">0</div><div class="label">累计脱敏</div></div>
    <div class="card"><div class="num" id="requests">0</div><div class="label">请求数</div></div>
    <div class="card"><div class="num" id="cats">0</div><div class="label">启用的类别</div></div>
  </div>

  <div class="panel" id="guide">
    <h3>接入引导(检测 + 手动指引)</h3>
    <div id="agents">检测中…</div>
    <h3 style="margin-top:14px">Codex 手动接入步骤</h3>
    <ol style="font-size:13px;color:#475467;padding-left:20px;margin:8px 0">
      <li>编辑 <code class="mono">~/.codex/config.toml</code>(先备份)</li>
      <li>追加以下配置片段并保存</li>
    </ol>
    <pre>export LLM_SANITIZER_KEY="你的上游API密钥"
# ~/.codex/config.toml 追加:
[model_providers.llm-sanitizer]
name = "LLM Sanitizer"
base_url = "http://127.0.0.1:8790/v1"
env_key = "LLM_SANITIZER_KEY"
wire_api = "responses"

model_provider = "llm-sanitizer"</pre>
    <p style="font-size:13px;color:#475467">3. 重启 Codex,发送一条含测试隐私的消息(如"申请人张三,电话 13912345678"),回到本页确认下方事件区出现脱敏记录。</p>
  </div>

  <div class="panel" id="settings">
    <h3>设置</h3>
    <form id="form">
      <label>上游 LLM 地址</label>
      <input type="text" id="upstream" placeholder="https://api.deepseek.com">
      <label>上游 API 密钥(留空 = 不修改;保存在本机,权限 600)</label>
      <input type="password" id="key" placeholder="sk-...">
      <div class="preset">脱敏类别预设:
        <button type="button" class="btn" onclick="preset('all')">高敏感(全开)</button>
        <button type="button" class="btn" onclick="preset('office')">办公</button>
        <button type="button" class="btn" onclick="preset('custom')">自定义</button>
      </div>
      <div id="catsbox" style="margin-top:8px"></div>
      <div class="warn">关闭某个类别后,该类信息将<b>明文发送给云端</b>——请确认这是你的本意。保存后重启网关生效。</div>
      <div style="margin-top:14px">
        <button type="submit" class="btn btn-p">保存设置</button>
        <span class="ok" id="saved"></span>
      </div>
    </form>
  </div>

  <h2>按类别分布</h2><div id="bars"></div>
  <h2 id="events">最近脱敏事件(不含明文)</h2>
  <table><thead><tr><th>时间</th><th>类别</th><th>占位符</th><th>请求</th></tr></thead>
  <tbody id="tbody_events"></tbody></table>
  <h2>最近请求</h2>
  <table><thead><tr><th>时间</th><th>方法</th><th>路径</th><th>新增脱敏</th></tr></thead>
  <tbody id="tbody_reqs"></tbody></table>
</main>
<script>
const ALL_CATS = ["姓名","身份证号","手机号","座机号","邮箱","统一社会信用代码","公司名称","司法机关","地址","出生日期","银行账号","案号","车牌号","证件号","密钥令牌"];
const OFFICE = ["姓名","手机号","邮箱","公司名称","银行账号","地址"];
function esc(s) { return String(s==null?'':s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function refresh() {
  fetch('/api/status').then(r=>r.json()).then(d=>{
    document.getElementById('live').className = '';
    document.getElementById('live').textContent = '运行中';
    document.getElementById('total').textContent = d.total_masked;
    document.getElementById('requests').textContent = d.requests;
    document.getElementById('cats').textContent = (d.categories ? d.categories.length : ALL_CATS.length) + '/' + ALL_CATS.length;
    const bars = document.getElementById('bars');
    const max = Math.max(1, ...Object.values(d.by_category));
    bars.innerHTML = Object.entries(d.by_category).map(([k,v]) =>
      '<div style="margin-bottom:8px;font-size:13px">' + k + ' <span style="float:right">' + v + '</span>' +
      '<div class="bar"><i style="width:' + (v/max*100) + '%"></i></div></div>').join('');
    document.getElementById('tbody_events').innerHTML = d.events.map(e =>
      '<tr><td>' + esc(e.ts) + '</td><td><span class="tag">' + esc(e.category) + '</span></td>' +
      '<td class="mono">' + esc(e.token) + '</td><td>' + esc(e.path || '') + '</td></tr>').join('');
    document.getElementById('tbody_reqs').innerHTML = d.reqs.map(e =>
      '<tr><td>' + esc(e.ts) + '</td><td>' + esc(e.method) + '</td><td class="mono">' + esc(e.path) + '</td>' +
      '<td>' + esc(e.new_findings) + '</td></tr>').join('');
  }).catch(()=>{
    document.getElementById('live').className = 'off';
    document.getElementById('live').textContent = '看板服务异常';
  });
}

function loadAgents() {
  fetch('/api/agents').then(r=>r.json()).then(d=>{
    document.getElementById('agents').innerHTML = d.agents.map(a =>
      '<div class="agent"><span>' + a.name +
      ' <span class="det ' + (a.detected?'y':'n') + '">' + (a.detected ? '已检测到 ' + a.path : '未检测到') +
      '</span></span></div>').join('');
  }).catch(()=>{ document.getElementById('agents').textContent = '检测失败'; });
}

function preset(p) {
  const set = p==='all' ? ALL_CATS : p==='office' ? OFFICE : currentChecks();
  document.querySelectorAll('#catsbox input').forEach(c => c.checked = set.includes(c.value));
}
function currentChecks() {
  return [...document.querySelectorAll('#catsbox input')].filter(c=>c.checked).map(c=>c.value);
}
function renderCats(selected) {
  document.getElementById('catsbox').innerHTML = ALL_CATS.map(c =>
    '<label class="chk"><input type="checkbox" value="' + c + '"' + (selected.includes(c)?' checked':'') + '> ' + c + '</label>').join('');
}

function loadSettings() {
  fetch('/api/settings').then(r=>r.json()).then(d=>{
    document.getElementById('upstream').value = d.upstream || '';
    renderCats(d.categories || ALL_CATS);
  }).catch(()=>{});
}

document.getElementById('form').addEventListener('submit', e=>{
  e.preventDefault();
  fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type':'application/json','X-Local-Token':'local'},
    body: JSON.stringify({
      upstream: document.getElementById('upstream').value.trim(),
      key: document.getElementById('key').value.trim(),
      categories: currentChecks()
    })
  }).then(r=>r.json()).then(d=>{
    document.getElementById('saved').textContent = d.ok ? '已保存(重启后生效)' : ('失败:' + (d.error||''));
    document.getElementById('key').value = '';
  }).catch(()=>{ document.getElementById('saved').textContent = '保存失败'; });
});

setInterval(refresh, 2000);
refresh();
loadAgents();
loadSettings();
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
        if not _host_ok(self.headers):
            self._json(403, {"error": "forbidden host"})
            return
        if not _origin_ok(self.headers):
            self._json(403, {"error": "forbidden origin"})
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            events = tail_events(str(config.events_path()), limit=300)
            masked = [e for e in events if e.get("kind") == "mask"]
            reqs = [e for e in events if e.get("kind") == "request"]
            by_cat = {}
            for e in masked:
                c = e.get("category", "?")
                by_cat[c] = by_cat.get(c, 0) + 1
            from .masker import ALL_CATEGORIES

            settings = config.load_settings()
            cats = settings.get("categories") or ALL_CATEGORIES
            self._json(200, {
                "total_masked": len(masked),
                "requests": len(reqs),
                "by_category": by_cat,
                "categories": cats,
                "events": list(reversed(masked[-20:])),
                "reqs": list(reversed(reqs[-15:])),
                "updated": time.strftime("%H:%M:%S"),
            })
        elif path == "/api/agents":
            self._json(200, {"agents": config_manager.detect_agents()})
        elif path == "/api/settings":
            s = config.load_settings()
            self._json(200, {
                "upstream": s.get("upstream", ""),
                "key_set": bool(s.get("key")),
                "categories": s.get("categories"),
            })
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not _host_ok(self.headers):
            self._json(403, {"error": "forbidden host"})
            return
        if not _origin_ok(self.headers):
            self._json(403, {"error": "forbidden origin"})
            return
        path = urlparse(self.path).path
        if path != "/api/settings":
            self._json(404, {"error": "not found"})
            return
        # 写接口保护(FR-8):要求本地自定义头,浏览器跨站无法携带
        if not self.headers.get("X-Local-Token"):
            self._json(403, {"error": "missing local token"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            self._json(400, {"error": "bad json"})
            return
        settings = config.load_settings()
        if data.get("upstream"):
            settings["upstream"] = str(data["upstream"]).strip()
        if data.get("key"):
            settings["key"] = str(data["key"]).strip()
        if isinstance(data.get("categories"), list):
            settings["categories"] = [str(c) for c in data["categories"]]
        try:
            config.save_settings(settings)
        except Exception as e:
            self._json(500, {"error": f"save failed: {e}"})
            return
        self._json(200, {"ok": True})

    def _send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")


def create_dashboard_server(port=None):
    return ThreadingHTTPServer(
        (config.host(), port if port is not None else config.dashboard_port()), DashboardHandler
    )
