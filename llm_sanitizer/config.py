"""配置中心:端口、上游、数据目录、类别(全部可被界面设置覆盖)。

优先级(FR-15):settings.json(界面设置) > 环境变量 > 内置默认值。
"""

import json
import os
import tempfile
from pathlib import Path


def _windows_data_dir(localappdata=None) -> str:
    """Windows 数据目录字符串:%LOCALAPPDATA%\\llm-sanitizer(纯函数,可测)。"""
    base = localappdata or os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return os.path.join(base, "llm-sanitizer")


def data_dir() -> Path:
    """数据目录:LLM_SANITIZER_HOME 优先;Windows 用 %LOCALAPPDATA%\\llm-sanitizer
    (用户私有目录自带 ACL 隔离,承担 map.json 600 权限的语义);其余 ~/.llm-sanitizer。"""
    env = os.environ.get("LLM_SANITIZER_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(_windows_data_dir())
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


def policy_path() -> Path:
    """组织策略(v0.5):enforced_categories / blocked_categories / retention_days。
    由管理员/组织统一维护,优先级高于用户设置。"""
    return data_dir() / "policy.json"


DEFAULT_POLICY = {
    "enforced_categories": [],   # 组织强制开启的类别(用户不可关闭)
    "blocked_categories": [],    # 组织强制关闭的类别(用户不可开启)
    "retention_days": 90,        # 事件留存天数(审计导出与启动清理)
}


def load_policy() -> dict:
    """读取组织策略;不存在/异常返回默认(全量由用户控制)。"""
    try:
        with open(policy_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULT_POLICY)
        out = dict(DEFAULT_POLICY)
        out.update(data)
        if not isinstance(out.get("enforced_categories"), list):
            out["enforced_categories"] = []
        if not isinstance(out.get("blocked_categories"), list):
            out["blocked_categories"] = []
        return out
    except Exception:
        return dict(DEFAULT_POLICY)


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
    """网关端口:环境变量(运维/测试覆盖) > settings.json(界面/--port 持久化) > 8790。"""
    env = os.environ.get("LLM_SANITIZER_PORT")
    if env:
        return int(env)
    return int(load_settings().get("gateway_port") or 8790)


def dashboard_port() -> int:
    """看板端口:环境变量 > settings.json(--dashboard-port 持久化) > 8791。"""
    env = os.environ.get("LLM_SANITIZER_DASHBOARD_PORT")
    if env:
        return int(env)
    return int(load_settings().get("dashboard_port") or 8791)


def set_gateway_port(port: int) -> None:
    """持久化网关端口(start --port 写回,下次启动/开机自启默认使用)。"""
    s = load_settings()
    s["gateway_port"] = int(port)
    save_settings(s)


def set_dashboard_port(port: int) -> None:
    """持久化看板端口(start --dashboard-port 写回)。"""
    s = load_settings()
    s["dashboard_port"] = int(port)
    save_settings(s)


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
    """生效类别 = 用户设置 ∩ (组织策略强制项)。优先级:
    策略 enforced > 用户设置 > 环境变量(全量);策略 blocked 强制关闭。"""
    from .masker import ALL_CATEGORIES

    s = load_settings()
    cats = s.get("categories")
    enabled = set(cats) if cats is not None else set(ALL_CATEGORIES)
    policy = load_policy()
    enforced = set(policy.get("enforced_categories") or [])
    blocked = set(policy.get("blocked_categories") or [])
    enabled = (enabled | enforced) - blocked  # 强制开 + 用户开,再减去强制关
    return {c for c in ALL_CATEGORIES if c not in enabled}


def enabled_categories() -> set:
    """生效的启用类别(供控制台显示/审计)。"""
    from .masker import ALL_CATEGORIES

    return set(ALL_CATEGORIES) - disabled_categories()


def retention_days() -> int:
    """组织策略事件留存天数(默认 90)。"""
    try:
        return max(1, int(load_policy().get("retention_days") or 90))
    except (TypeError, ValueError):
        return 90


def host() -> str:
    return "127.0.0.1"


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
