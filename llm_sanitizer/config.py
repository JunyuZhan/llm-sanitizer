"""配置中心：端口、上游、数据目录（全部可用环境变量覆盖）。"""

import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("LLM_SANITIZER_HOME", str(Path.home() / ".llm-sanitizer")))


def map_path() -> Path:
    return data_dir() / "map.json"


def events_path() -> Path:
    return data_dir() / "events.jsonl"


def log_path() -> Path:
    return data_dir() / "gateway.log"


def gateway_port() -> int:
    return int(os.environ.get("LLM_SANITIZER_PORT", "8790"))


def dashboard_port() -> int:
    return int(os.environ.get("LLM_SANITIZER_DASHBOARD_PORT", "8791"))


def upstream() -> str:
    return os.environ.get("LLM_SANITIZER_UPSTREAM", "https://api.openai.com/v1")


def upstream_key() -> str:
    return os.environ.get("LLM_SANITIZER_KEY", "")


def host() -> str:
    return "127.0.0.1"


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
