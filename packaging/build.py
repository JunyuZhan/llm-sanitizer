#!/usr/bin/env python3
"""一键构建独立可执行文件(免 Python 环境)。

用法:
    pip install pyinstaller
    python packaging/build.py

产物:dist/llm-sanitizer(macOS/Linux)或 dist/llm-sanitizer.exe(Windows)。
签名/公证说明见 packaging/llm_sanitizer.spec 头部。
"""

import subprocess
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parent / "llm_sanitizer.spec"


def main() -> int:
    print(f"[build] 使用 {SPEC}")
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=str(SPEC.parent),
    )
    if r.returncode != 0:
        print("[build] 失败:PyInstaller 返回非零(请先 pip install pyinstaller)")
        return r.returncode
    print("[build] 完成:dist/llm-sanitizer" + (".exe" if sys.platform == "win32" else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
