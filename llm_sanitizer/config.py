"""配置中心:端口、上游、数据目录、类别(全部可被界面设置覆盖)。

优先级(FR-15):settings.json(界面设置) > 环境变量 > 内置默认值。
"""

import json
import os
import tempfile
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("LLM_SANITIZER_HOME", str(Path.home() / ".llm-sanitizer")))


def map_path() -> Path:
    return data_dir() / "map.json"


def events_path() -> Path:
    return data_dir() / "events.jsonl"


def log_path() -> Path:
    return data_dir() / "gateway.log"


def settings_path() -> Path:
    """控制台界面设置(FR-13):upstream / key / categories。"""
    return data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    """原子写 + chmod 600(敏感配置统一落盘要求)。"""
    path = str(settings_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def gateway_port() -> int:
    return int(os.environ.get("LLM_SANITIZER_PORT", "8790"))


def dashboard_port() -> int:
    return int(os.environ.get("LLM_SANITIZER_DASHBOARD_PORT", "8791"))


def upstream() -> str:
    s = load_settings()
    if s.get("upstream"):
        return s["upstream"]
    return os.environ.get("LLM_SANITIZER_UPSTREAM", "https://api.openai.com/v1")


def upstream_key() -> str:
    s = load_settings()
    if s.get("key"):
        return s["key"]
    return os.environ.get("LLM_SANITIZER_KEY", "")


def disabled_categories() -> set:
    """从设置读取启用的类别,反推禁用集合。未配置 = 全量。"""
    from .masker import ALL_CATEGORIES

    s = load_settings()
    cats = s.get("categories")
    if cats is None:
        return set()
    enabled = set(cats)
    return {c for c in ALL_CATEGORIES if c not in enabled}


def host() -> str:
    return "127.0.0.1"


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
