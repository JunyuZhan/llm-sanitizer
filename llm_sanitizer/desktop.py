"""桌面轻包(v0.5,可选特性):原生窗口打开控制台,退出时关闭网关/看板。

设计(见 docs/开发文档.md ADR-12/14):
- 界面层与内核解耦:网关/看板仍是纯标准库,本模块只是"打开浏览器窗口的壳"
- **可选依赖,ADR-1 核心零依赖不受影响**:
    pip install llm-sanitizer-gateway[desktop]   # pywebview
- 定位:小白用户免浏览器标签页——"一键打开看数据,关窗即走";
  v0.5.3 起:后台已有服务(开机自启/手动 start)时直接开窗看数据,
  不重复起服务,关闭窗口也不影响后台服务(那是 launchd 托管的)。
"""

from __future__ import annotations

import threading

from . import config, dashboard, gateway

try:
    import webview  # noqa: F401

    _HAS_WEBVIEW = True
except ImportError:  # 可选依赖缺失,核心包不受影响
    webview = None
    _HAS_WEBVIEW = False


def available() -> bool:
    """是否安装了 [desktop] 可选依赖(pywebview)。"""
    return _HAS_WEBVIEW


def install_hint() -> str:
    return (
        "桌面窗口是可选功能,需要:\n"
        "  pip install llm-sanitizer-gateway[desktop]\n"
        "(macOS 会自动安装 pyobjc 依赖;核心包零依赖不受影响)"
    )


def _open_window(title: str, url: str) -> bool:
    """打开原生窗口;返回 False 表示窗口启动失败(如无图形环境)。"""
    try:
        webview.create_window(title, url, width=1120, height=780)
        webview.start()
    except Exception as e:
        print(f"[llm-sanitizer] 桌面窗口启动失败: {e}(无图形环境时请用 start 命令)")
        return False
    return True


def run() -> bool:
    """打开控制台原生窗口。

    三种情形:
    - 后台已有服务(probe=self,如开机自启/手动 start 在跑):直接开窗看数据,
      不重复起服务;关闭窗口不停止后台服务。
    - 端口被其他程序占用(probe=other):给出可操作提示,不开窗。
    - 空闲:自行启动网关+看板再开窗;窗口关闭即停止本次启动的服务。

    返回 False 表示缺少 pywebview 或启动失败(调用方负责提示)。
    """
    if not _HAS_WEBVIEW:
        return False
    config.ensure_dirs()
    gw_port = config.gateway_port()
    db_port = config.dashboard_port()
    url = f"http://127.0.0.1:{db_port}"
    # 后台已有服务:直接开窗看数据(服务是外部托管的,不归本窗口管)
    gw_state = gateway.probe_port(gw_port)
    if gw_state == "self":
        print(f"[llm-sanitizer] 服务已在运行(网关 {gw_port}),直接打开看板窗口。")
        print(f"[llm-sanitizer] 关闭窗口即退出,后台服务保持运行。")
        return _open_window("LLM Sanitizer", url)
    if gw_state == "other":
        print(f"[llm-sanitizer] 端口 {gw_port} 已被其他程序占用,桌面模式无法启动。")
        print(f"[llm-sanitizer] 先停掉占用该端口的程序,或用 llm-sanitizer start --port 8792")
        return False
    db_state = gateway.probe_port(db_port)
    if db_state == "other":
        print(f"[llm-sanitizer] 看板端口 {db_port} 已被其他程序占用,桌面模式无法启动。")
        print(f"[llm-sanitizer] 先停掉占用该端口的程序,或用 llm-sanitizer start --dashboard-port 8792")
        return False
    # 空闲:本次启动的服务归本窗口管,关窗即停
    gateway.init_state()
    try:
        gs = gateway.create_gateway_server()
        ds = dashboard.create_dashboard_server()
    except OSError as e:
        print(f"[llm-sanitizer] 启动失败:端口不可用({e}).")
        return False
    threading.Thread(target=gs.serve_forever, daemon=True).start()
    threading.Thread(target=ds.serve_forever, daemon=True).start()
    print(f"[llm-sanitizer] 桌面控制台 {url}(关闭窗口即退出并停止服务)")
    ok = _open_window("LLM Sanitizer", url)
    try:
        gs.shutdown()
    except Exception:
        pass
    try:
        ds.shutdown()
    except Exception:
        pass
    return ok
