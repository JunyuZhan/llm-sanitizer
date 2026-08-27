"""Agent 配置一键接入 / 还原(FR-12,v0.2+)。

原则:任何修改先备份、界面可见、可一键还原;绝不静默改配置。

- `detect_agents()`:只读检测本机 Agent 与配置路径(含 applied 状态)
- `backup()`:备份原配置(时间戳,权限 600)
- `apply()`:写入网关 base_url(Codex TOML 文本级安全改写,兼容 Python 3.9,
  不依赖 tomllib;已接入则幂等跳过)
- `restore()`:从最新备份还原并移除该备份
- `list_backups()`:列出某 agent 的备份

OpenClaw 配置格式多变,自动写入留待社区贡献(检测与手动指引可用)。
"""

import json
import os
import re
import shutil
import time
from pathlib import Path

from . import config

def _gateway_base() -> str:
    """网关 base_url,动态取持久化端口(settings.json/env 可能已改默认 8790)。"""
    return f"http://127.0.0.1:{config.gateway_port()}/v1"

# Codex config.toml 片段。
# 注意 TOML 规范:根级键(model_provider)必须声明在任何 [table] 头之前——
# 追加到文件末尾会落入最后一个表内,导致一键接入"显示成功、实际不生效"。
# 因此 apply() 把根键插入首个 '[' 之前,provider 表追加到末尾。
def _codex_provider_table() -> str:
    base = _gateway_base()
    return f"""\
[model_providers.llm-sanitizer]
name = "LLM Sanitizer"
base_url = "{base}"
env_key = "LLM_SANITIZER_KEY"
wire_api = "responses"
"""

CODEX_ROOT_KEY = 'model_provider = "llm-sanitizer"\n'

# 根级(首个 [table] 之前)model_provider 键:双引号或单引号字面量均可
_ROOT_MP = re.compile(
    r"""^\s*model_provider\s*=\s*(?:"([^"]*)"|'([^']*)')\s*$""",
    re.MULTILINE,
)


def _first_table_pos(text):
    """返回第一个 [table] 表头的位置(支持文件以表头开头);无表返回 -1。"""
    pos = text.find("\n[")
    if pos == -1:
        pos = text.find("[")
    return pos


def _root_model_provider(text):
    """根级 model_provider 的值;未显式声明返回 None。

    文本级解析,兼容 Python 3.9(不依赖 tomllib)。只查首个 [table] 之前,
    避免把旧坏配置里"落在 provider 表内的键"误判为已接入。
    """
    pos = _first_table_pos(text)
    head = text if pos < 0 else text[:pos]
    m = _ROOT_MP.search(head)
    if not m:
        return None
    return m.group(1) or m.group(2)


def _replace_root_model_provider(text, value):
    """把根级 model_provider 替换为新值(只动第一个匹配,保留其余内容)。"""
    pos = _first_table_pos(text)
    head = text if pos < 0 else text[:pos]
    rest = text[pos:] if pos >= 0 else ""
    new_head = _ROOT_MP.sub(lambda m: f'model_provider = "{value}"', head, count=1)
    return new_head + rest


def _remove_legacy_root_key_from_table(text):
    """删除 [model_providers.llm-sanitizer] 表内残留的 model_provider 键。

    旧版 connect(≤v0.3)把根键误写进了表内——该键在表内无效,清理后
    配置与"根键在表前、表内无该键"的规范一致(备份仍保留原始现场)。
    """
    marker = "[model_providers.llm-sanitizer]"
    pos = text.find(marker)
    if pos == -1:
        return text
    end = text.find("\n[", pos + len(marker))
    if end == -1:
        end = len(text)
    seg = text[pos:end]
    new_seg = re.sub(r"(?m)^[ \t]*model_provider[ \t]*=.*\n?", "", seg)
    return text[:pos] + new_seg + text[end:]


def _config_path(agent_id):
    home = Path.home()
    if agent_id == "codex":
        return home / ".codex" / "config.toml"
    if agent_id == "claude":
        return home / ".claude" / "settings.json"
    if agent_id == "gemini":
        return home / ".gemini" / "settings.json"
    if agent_id == "workbuddy":
        return home / ".workbuddy"
    if agent_id == "openclaw":
        return home / ".openclaw" / "config.json"
    if agent_id == "opencode":
        return home / ".opencode"
    return None


# 检测矩阵:(id, 显示名, 配置路径, CLI 名, 是否支持自动接入)
_AGENT_PROBES = [
    ("codex", "Codex CLI", ".codex/config.toml", "codex", True),
    ("claude", "Claude Code", ".claude/settings.json", "claude", True),
    ("gemini", "Gemini CLI", ".gemini/settings.json", "gemini", False),
    ("workbuddy", "WorkBuddy", ".workbuddy", "workbuddy", False),
    ("openclaw", "OpenClaw", ".openclaw/config.json", "openclaw", False),
    ("opencode", "OpenCode", ".opencode", "opencode", False),
]


def _claude_applied(text: str) -> bool:
    """Claude Code 是否已接入:env.ANTHROPIC_BASE_URL 指向本机网关。"""
    try:
        obj = json.loads(text)
        base = (obj.get("env") or {}).get("ANTHROPIC_BASE_URL") or ""
    except Exception:
        return False
    return base.startswith("http://127.0.0.1:") or base.startswith("http://localhost:")


def detect_agents() -> list:
    """检测本机常见 AI 工具(Agent)的安装情况(只读),返回:
    [{"id", "name", "detected", "applied", "auto", "path"}, ...]

    detected = 配置文件存在 或 CLI 在 PATH;applied = 已接入本网关。
    auto=True 表示支持一键接入(Codex TOML / Claude Code JSON);
    其余检测展示、手动配置(Gemini 等接入方式待版本完善)。
    """
    home = Path.home()
    result = []
    for pid, name, rel, cli, auto in _AGENT_PROBES:
        path = _config_path(pid)
        exists = path is not None and path.exists()
        has_cli_cmd = shutil.which(cli) is not None
        detected = exists or has_cli_cmd
        applied = False
        if exists:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if pid == "codex":
                    applied = (
                        "[model_providers.llm-sanitizer]" in text
                        and _root_model_provider(text) == "llm-sanitizer"
                    )
                elif pid == "claude" and path.name == "settings.json":
                    applied = _claude_applied(text)
            except Exception:
                pass
        result.append({
            "id": pid,
            "name": name,
            "detected": detected,
            "applied": applied,
            "auto": auto,
            "path": str(path) if path else "",
            "cli": has_cli_cmd,
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
    已接入时幂等跳过(不再产生新备份)。

    自愈(v0.5.2+):识别旧版坏配置——provider 表存在但根级 model_provider
    缺失(旧 connect 把键写进了表内,Codex 实际未切换),重跑 connect 会
    补上根键并保留表;根级已声明其他 provider(如 openai)则替换为
    llm-sanitizer(原值可由 disconnect 从备份还原)。"""
    if agent_id == "claude":
        return _apply_claude()
    if agent_id != "codex":
        raise ValueError(f"暂不支持自动接入 {agent_id}(请手动配置)")
    src = _config_path("codex")
    if not src or not src.exists():
        raise FileNotFoundError("未找到 ~/.codex/config.toml")
    text = src.read_text(encoding="utf-8")
    has_table = "[model_providers.llm-sanitizer]" in text
    root_provider = _root_model_provider(text)
    if has_table and root_provider == "llm-sanitizer":
        return {"applied": True, "already": True, "backup": ""}
    bak = backup("codex")
    if root_provider is not None:
        # 根级已声明其他 provider:替换为 llm-sanitizer(接入语义)
        new_text = _replace_root_model_provider(text, "llm-sanitizer")
    else:
        # 根键必须声明在任何 [table] 之前:插入第一个 '[' 之前(保留头部注释)
        first_table = _first_table_pos(text)
        if first_table >= 0:
            prefix = text[:first_table]
            if prefix and not prefix.endswith("\n"):
                prefix += "\n"
            new_text = prefix + CODEX_ROOT_KEY + text[first_table:]
        else:
            new_text = text + ("\n" if text and not text.endswith("\n") else "") + CODEX_ROOT_KEY
    if has_table:
        # 旧坏配置自愈:清掉表内残留的 model_provider 键(无效但脏)
        new_text = _remove_legacy_root_key_from_table(new_text)
    else:
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += "\n" + _codex_provider_table()
    src.write_text(new_text, encoding="utf-8")
    try:
        os.chmod(src, 0o600)
    except OSError:
        pass
    return {"applied": True, "already": False, "backup": str(bak)}


def _apply_claude() -> dict:
    """Claude Code 一键接入:settings.json 写入 env.ANTHROPIC_BASE_URL 指向本网关。

    保留用户原有字段(模型、权限等),只合并 env;已接入则幂等跳过。
    """
    src = _config_path("claude")
    if not src or not src.exists():
        raise FileNotFoundError("未找到 ~/.claude/settings.json")
    base = _gateway_base()
    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            obj = {}
    except Exception:
        obj = {}
    env = obj.get("env") or {}
    if isinstance(env, dict) and env.get("ANTHROPIC_BASE_URL") == base:
        return {"applied": True, "already": True, "backup": ""}
    bak = backup("claude")
    env = dict(env)
    env["ANTHROPIC_BASE_URL"] = base
    env["ANTHROPIC_AUTH_TOKEN"] = "llm-sanitizer-local"  # 网关仅做本地校验,不真正鉴权
    obj["env"] = env
    _atomic_write_json(src, obj)
    return {"applied": True, "already": False, "backup": str(bak)}


def _atomic_write_json(path: Path, obj: dict) -> None:
    """原子写 JSON + chmod 600(与 config.save_settings 同语义)。"""
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


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
