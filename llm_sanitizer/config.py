"""配置中心:端口、上游、数据目录、类别(全部可被界面设置覆盖)。

优先级(FR-15):settings.json(界面设置) > 环境变量 > 内置默认值。
"""

import json
import os
import tempfile
from pathlib import Path


def data_dir() -> Path:
    """数据目录:LLM_SANITIZER_HOME 优先;Windows 用 %LOCALAPPDATA%\\llm-sanitizer
    (用户私有目录自带 ACL 隔离,承担 map.json 600 权限的语义);其余 ~/.llm-sanitizer。"""
    env = os.environ.get("LLM_SANITIZER_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(os.path.join(base, "llm-sanitizer"))
    return Path.home() / ".llm-sanitizer"


def map_path() -> Path:
    return data_dir() / "map.json"


def events_path() -> Path:
    return data_dir() / "events.jsonl"


def log_path() -> Path:
    return data_dir() / "gateway.log"


def settings_path() -> Path:
    """控制台界面设置(FR-13):upstream / key / categories。"""
    return data_dir() / "settings.json"


def wordlist_path() -> Path:
    """自定义敏感词表(v0.2):每行一个词,可 `词|类别`。"""
    return data_dir() / "wordlist.txt"


def load_wordlist_file() -> list:
    """读取用户词表;不存在/异常返回空(不崩溃)。"""
    from .masker import load_wordlist_file as _load

    return _load(wordlist_path())


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
