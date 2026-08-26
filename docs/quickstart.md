# Quick Start

Get from zero to "my agent is masked" in about five minutes.

[中文版](quickstart.zh-CN.md)

## 1. Prerequisites

- **Python 3.9+** (no third-party packages are required)
- macOS or Linux
- An account/key for the LLM provider your agent will talk to

## 2. Install

Two ways. **Once the PyPI package is published (part of v0.1), use pip:**

```bash
pip install llmsanitize
llm-sanitizer start
```

**Source mode:**

```bash
git clone https://github.com/JunyuZhan/llm-sanitizer.git
cd llm-sanitizer
python3 -m llm_sanitizer start
```

## 3. Configure

Everything is configurable via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_SANITIZER_UPSTREAM` | `https://api.openai.com/v1` | Upstream LLM base URL. Both OpenAI-style (base ends in `/v1`) and DeepSeek-style (no `/v1`) work |
| `LLM_SANITIZER_KEY` | *(empty)* | API key the gateway forwards upstream. Optional if your agent already sends its own `Authorization` header |
| `LLM_SANITIZER_PORT` | `8790` | Gateway port (listens on `127.0.0.1` only) |
| `LLM_SANITIZER_DASHBOARD_PORT` | `8791` | Dashboard port |
| `LLM_SANITIZER_HOME` | `~/.llm-sanitizer` | Data directory (`map.json`, `events.jsonl`, logs) |
| `LLM_SANITIZER_CATEGORIES` | *(empty = all)* | Enabled masking categories, comma-separated, e.g. `姓名,手机号,银行账号` (FR-15) |

```bash
export LLM_SANITIZER_UPSTREAM="https://api.deepseek.com"
export LLM_SANITIZER_KEY="sk-your-key-here"
python3 -m llm_sanitizer start
```

You should see:

```
[llm-sanitizer] 网关  http://127.0.0.1:8790/v1
[llm-sanitizer] 看板  http://127.0.0.1:8791
[llm-sanitizer] 上游  https://api.deepseek.com
```

## 4. Point your agent at the gateway

The universal pattern: **set the agent's base URL to `http://127.0.0.1:8790/v1`**. Any OpenAI-compatible client works.

Step-by-step for **Codex**, **WorkBuddy**, and **OpenClaw**: see [Agent integration](AGENTS.md).

## 5. Verify it actually works

1. Send a test message from your agent, e.g. *"申请人张三，电话 13912345678"*.
2. Open the dashboard at `http://127.0.0.1:8791`.
3. Within ~2 seconds you should see new mask events: category `姓名`, `手机号`, placeholders `[姓名_1]`, `[手机号_1]`.

No events? Check the [troubleshooting](#7-troubleshooting) section.

## 6. Daily use & CLI

| Command | What it does |
|---|---|
| `python3 -m llm_sanitizer start` | Start gateway + dashboard (foreground) |
| `python3 -m llm_sanitizer status` | Show port status, upstream, and cumulative stats |
| `python3 -m llm_sanitizer mask <file>` | Mask a single text file (CSV/JSON/SQL/code…) without a gateway |
| `python3 -m llm_sanitizer restore <file> --map <map.json>` | Restore a masked file using its mapping |

The **dashboard** shows: cumulative masked count, per-category distribution, recent mask events (placeholders only — never plaintext), and recent requests.

For lawyers: you can pre-mask a file locally, then hand the masked version to an agent — see [LEGAL.md](LEGAL.md). Note: CLI masking uses its own mapping; don't mix it with gateway mappings (see [FAQ](faq.zh-CN.md#mapjson-在-cli-和网关之间混用会怎样)).

## 7. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `No module named llm_sanitizer` | Not running from the repo root or missing `PYTHONPATH` — use pip install or run from the repo root |
| Dashboard shows no events | Agent is not actually routing through the gateway. Check the agent's base URL; some desktop apps use WebSocket and bypass HTTP (see [SECURITY](SECURITY.md)) |
| Dashboard shows no events | Agent is not actually routing through the gateway. Check the agent's base URL; some desktop apps use WebSocket and bypass HTTP (known limit R1) |
| `upstream unreachable` | Wrong `LLM_SANITIZER_UPSTREAM` or network blocked |
| `401` from upstream | `LLM_SANITIZER_KEY` missing or invalid; or the agent's own key isn't being forwarded |
| Response contains placeholders like `[地址_1]` | Tool-call arguments restore is a known gap in v0.1 (see [开发文档](../docs/开发文档.md)) |

## 8. Upgrade & uninstall

**Upgrade (pip install, recommended):**

```bash
pip install --upgrade llmsanitize
# if auto-start is installed, restart the service to pick up the new version:
./install.sh --uninstall && ./install.sh
```

**Upgrade (source install):** `cd llm-sanitizer && git pull`, then restart the auto-start service the same way.

**Check for updates:** `llm-sanitizer upgrade` queries PyPI and prints upgrade instructions; `start` also checks in the background.

> **Data compatibility:** upgrading never loses mappings or stats — the `map.json` token format is stable (ADR-2); old mappings still restore after upgrade.

**Uninstall (removes services, config, and data):**

```bash
./install.sh --uninstall      # or: llm-sanitizer install --uninstall
rm -rf ~/.llm-sanitizer       # mapping + events — treat map.json as sensitive data!
```

Then set your agent's base URL back to the original provider.

**Before trusting this tool with real documents, read [SECURITY.md](SECURITY.md).**
