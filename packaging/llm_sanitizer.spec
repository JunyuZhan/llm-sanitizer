# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec:构建免 Python 环境的单文件 llm-sanitizer 可执行程序。

用法:
    pip install pyinstaller pywebview        # pywebview:桌面窗口打包需要
    python packaging/build.py                # 或 pyinstaller packaging/llm_sanitizer.spec

产物:
    dist/llm-sanitizer        (macOS / Linux)
    dist/llm-sanitizer.exe    (Windows)

包含(全部命令 + 桌面窗口):
- CLI 全部命令:start/desktop/status/mask/restore/connect/audit-export 等
- **桌面窗口(pywebview)已打入**:`llm-sanitizer desktop` 在独立包中直接可用
- OCR(tesseract)为系统依赖,不内置,需要时 pip 安装 [ocr]

说明(如实标注):
- macOS 发布前需 ad-hoc 或 Developer ID 签名 + 公证(Gatekeeper):
      codesign --force --deep -s "Developer ID Application: ..." dist/llm-sanitizer
      xcrun notarytool submit dist/llm-sanitizer --keychain-profile ... --wait
- Windows 发布前需签名(否则 SmartScreen 拦截):signtool sign /a dist/llm-sanitizer.exe
- macOS 上 pywebview 依赖系统 WebKit 框架(系统自带,无需打包);
  pyobjc 相关框架由 collect_all('webview') 收集。
"""

from PyInstaller.utils.hooks import collect_all

# pywebview 资源(JS/CSS)与隐藏导入:macOS 需显式引入 cocoa 平台与 pyobjc 框架
webview_datas, webview_binaries, webview_hidden = collect_all("webview")

hiddenimports = [
    "llm_sanitizer.cli",
    "llm_sanitizer.config",
    "llm_sanitizer.config_manager",
    "llm_sanitizer.dashboard",
    "llm_sanitizer.desktop",
    "llm_sanitizer.events",
    "llm_sanitizer.formats",
    "llm_sanitizer.gateway",
    "llm_sanitizer.masker",
    "llm_sanitizer.ocr",
    "llm_sanitizer.websocket",
    "webview",
    "webview.platforms.cocoa",
    "webview.platforms.gtk",
] + webview_hidden

a = Analysis(
    ["../llm_sanitizer/__main__.py"],
    pathex=[".."],
    binaries=webview_binaries,
    datas=webview_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pydoc", "test", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="llm-sanitizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,          # CLI 工具,保留控制台输出
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
