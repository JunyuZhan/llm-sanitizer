"""桌面轻包(v0.5,可选特性):原生窗口打开控制台,退出时关闭网关/看板。

设计(见 docs/开发文档.md ADR-12/14):
- 界面层与内核解耦:网关/看板仍是纯标准库,本模块只是"打开浏览器窗口的壳"
- **可选依赖,ADR-1 核心零依赖不受影响**:
    pip install llm-sanitizer-gateway[desktop]   # pywebview
- 定位:小白用户免浏览器标签页;系统托盘/菜单栏常驻、独立安装包为 v0.5+ 增强
"""

from __future__ import annotations

import threading

from . import config, dashboard, gateway


def available() -> bool:
    """是否安装了 [desktop] 可选依赖(pywebview)。"""
    try:
        import webview  # noqa: F401

        return True
    except ImportError:
        return False


def install_hint() -> str:
    return (
        "桌面窗口是可选功能,需要:\n"
        "  pip install llm-sanitizer-gateway[desktop]\n"
        "(macOS 会自动安装 pyobjc 依赖;核心包零依赖不受影响)"
    )


def run() -> bool:
    """打开控制台原生窗口;窗口关闭时停止网关与看板。

    返回 False 表示缺少 pywebview(调用方负责提示)。
    """
    try:
        import webview
    except ImportError:
        return False
    config.ensure_dirs()
    gateway.init_state()
    gs = gateway.create_gateway_server()
    ds = dashboard.create_dashboard_server()
    threading.Thread(target=gs.serve_forever, daemon=True).start()
    threading.Thread(target=ds.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{config.dashboard_port()}"
    print(f"[llm-sanitizer] 桌面控制台 {url}(关闭窗口即退出)")
    try:
        webview.create_window("LLM Sanitizer", url, width=1120, height=780)
        webview.start()
    except Exception as e:
        print(f"[llm-sanitizer] 桌面窗口启动失败: {e}(无图形环境时请用 start 命令)")
        return False
    finally:
        try:
            gs.shutdown()
        except Exception:
            pass
        try:
            ds.shutdown()
        except Exception:
            pass
    return True
