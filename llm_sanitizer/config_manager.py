"""Agent 配置检测 / 一键接入。

v0.1(FR-11):只实现 `detect_agents()` —— 引导向导"检测 + 手动指引"只读本机,
不写入任何配置。
v0.2(FR-12):`backup()` / `apply()` / `restore()` 一键接入/还原,计划中。
"""

import shutil
from pathlib import Path


def detect_agents() -> list:
    """检测本机常见 Agent 的配置文件(只读),返回:
    [{"id", "name", "detected", "path", "hint"}, ...]
    """
    home = Path.home()
    probes = [
        ("codex", "Codex", home / ".codex" / "config.toml",
         "编辑 config.toml,新增 model_provider 指向 http://127.0.0.1:8790/v1"),
        ("openclaw", "OpenClaw", home / ".openclaw" / "config.json",
         "在模型提供方配置中把 base URL 指向 http://127.0.0.1:8790/v1"),
    ]
    result = []
    for pid, name, path, hint in probes:
        result.append({
            "id": pid,
            "name": name,
            "detected": path.exists(),
            "path": str(path),
            "hint": hint,
        })
    return result


def has_cli(name: str) -> bool:
    """本机是否安装了某 Agent 的 CLI(辅助检测)。"""
    return shutil.which(name) is not None
