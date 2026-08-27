"""Agent 配置一键接入 / 还原(FR-12,v0.2)。

原则:任何修改先备份、界面可见、可一键还原;绝不静默改配置。

- `detect_agents()`:只读检测本机 Agent 与配置路径(含 applied 状态)
- `backup()`:备份原配置(时间戳,权限 600)
- `apply()`:写入网关 base_url(Codex TOML 文本级安全改写,兼容 Python 3.9,
  不依赖 tomllib;已接入则幂等跳过)
- `restore()`:从最新备份还原并移除该备份
- `list_backups()`:列出某 agent 的备份

OpenClaw 配置格式多变,自动写入留待社区贡献(检测与手动指引可用)。
"""

import os
import shutil
import time
from pathlib import Path

from . import config

GATEWAY_BASE = "http://127.0.0.1:8790/v1"

# Codex config.toml 片段。
# 注意 TOML 规范:根级键(model_provider)必须声明在任何 [table] 头之前——
# 追加到文件末尾会落入最后一个表内,导致一键接入"显示成功、实际不生效"。
# 因此 apply() 把根键插入首个 '[' 之前,provider 表追加到末尾。
CODEX_MODEL_PROVIDER_TABLE = """\
[model_providers.llm-sanitizer]
name = "LLM Sanitizer"
base_url = "http://127.0.0.1:8790/v1"
env_key = "LLM_SANITIZER_KEY"
wire_api = "responses"
"""

CODEX_ROOT_KEY = 'model_provider = "llm-sanitizer"\n'


def _config_path(agent_id):
    home = Path.home()
    if agent_id == "codex":
        return home / ".codex" / "config.toml"
    if agent_id == "openclaw":
        return home / ".openclaw" / "config.json"
    return None


def detect_agents() -> list:
    """检测本机常见 Agent 的配置文件(只读),返回:
    [{"id", "name", "detected", "applied", "auto", "path"}, ...]
    auto=True 表示支持一键接入(Codex);OpenClaw 需手动配置。
    """
    home = Path.home()
    probes = [
        ("codex", "Codex", home / ".codex" / "config.toml", True),
        ("openclaw", "OpenClaw", home / ".openclaw" / "config.json", False),
    ]
    result = []
    for pid, name, path, auto in probes:
        applied = False
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                applied = "llm-sanitizer" in text
            except Exception:
                pass
        result.append({
            "id": pid,
            "name": name,
            "detected": path.exists(),
            "applied": applied,
            "auto": auto,
            "path": str(path),
        })
    return result


def has_cli(name: str) -> bool:
    """本机是否安装了某 Agent 的 CLI(辅助检测)。"""
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# 备份 / 接入 / 还原
# ---------------------------------------------------------------------------
def _backup_root() -> Path:
    return config.data_dir() / "agent-backups"


def backup(agent_id) -> Path:
    """备份配置文件(时间戳,权限 600);返回备份路径。"""
    src = _config_path(agent_id)
    if not src or not src.exists():
        raise FileNotFoundError(f"{agent_id} 配置文件不存在: {src}")
    dst_dir = _backup_root() / agent_id
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{src.name}.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(src, dst)
    try:
        os.chmod(dst, 0o600)
    except OSError:
        pass
    return dst


def list_backups(agent_id) -> list:
    d = _backup_root() / agent_id
    if not d.exists():
        return []
    return sorted(str(p) for p in d.iterdir() if p.is_file())


def apply(agent_id) -> dict:
    """一键接入:备份 → 写入网关地址。返回 {"applied", "already", "backup"}。
    已接入时幂等跳过(不再产生新备份)。"""
    if agent_id != "codex":
        raise ValueError(f"暂不支持自动接入 {agent_id}(OpenClaw 请手动配置)")
    src = _config_path("codex")
    if not src or not src.exists():
        raise FileNotFoundError("未找到 ~/.codex/config.toml")
    text = src.read_text(encoding="utf-8")
    if "[model_providers.llm-sanitizer]" in text:
        return {"applied": True, "already": True, "backup": ""}
    bak = backup("codex")
    # 根键必须声明在任何 [table] 之前:插入第一个 '[' 之前(保留头部注释)
    first_table = text.find("\n[")
    if first_table == -1:
        first_table = text.find("[")
    if first_table >= 0:
        new_text = text[:first_table] + "\n" + CODEX_ROOT_KEY + text[first_table:]
    else:
        new_text = text + ("\n" if text and not text.endswith("\n") else "") + CODEX_ROOT_KEY
    if not new_text.endswith("\n"):
        new_text += "\n"
    new_text += "\n" + CODEX_MODEL_PROVIDER_TABLE
    src.write_text(new_text, encoding="utf-8")
    try:
        os.chmod(src, 0o600)
    except OSError:
        pass
    return {"applied": True, "already": False, "backup": str(bak)}


def restore(agent_id) -> dict:
    """从最新备份还原并移除该备份。返回 {"restored", "path"}。"""
    backups = list_backups(agent_id)
    if not backups:
        raise FileNotFoundError(f"{agent_id} 没有可还原的备份")
    src = _config_path(agent_id)
    latest = Path(backups[-1])
    if src:
        shutil.copy2(latest, src)
        try:
            os.chmod(src, 0o600)
        except OSError:
            pass
    latest.unlink()
    return {"restored": True, "path": str(src)}
