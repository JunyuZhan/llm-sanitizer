# LLM Sanitizer

[![CI](https://github.com/JunyuZhan/llm-sanitizer/actions/workflows/ci.yml/badge.svg)](https://github.com/JunyuZhan/llm-sanitizer/actions/workflows/ci.yml)

**A local privacy gateway for AI traffic.** Before your AI agent (Codex, WorkBuddy, OpenClaw, Claude Code, Cline…) sends local files to a cloud LLM, LLM Sanitizer automatically replaces sensitive information — names, ID numbers, phone numbers, addresses, court names — with placeholders like `[姓名_1]`; on the way back it restores them precisely, and a **live dashboard** shows you exactly what was masked.

> Primary audience: lawyers, legal professionals, and anyone who hands local documents to an AI agent and worries about data leakage.

[🇨🇳 中文版 README](README.zh-CN.md)

---

## Project Status

> **v0.1 released · v0.2 in progress.** Local gateway, 15 Chinese-sensitive-data categories, live console, CLI, auto-start installer and CI are all in place — `pip install llm-sanitizer-gateway` to get started. v0.2 has landed **WebSocket transparent proxy** and **custom word lists**; format-preserving masking, one-click integration and more are in progress. Contributions welcome.

## Why

AI agents read local files (Word, Excel, PDF…) and send their contents to cloud models. Names, ID numbers, and court names leave your machine without you noticing. LLM Sanitizer adds a local gate before that happens:

```
Agent → [local gateway: mask] → cloud (sees only [姓名_1] placeholders)
Agent ← [local gateway: restore] ← cloud
            ↑
   live dashboard: watch every mask event
```

## Features

- **Local-first gateway** — listens on `127.0.0.1` only; no system proxy, no certificates, no global traffic interception
- **Chinese-sensitive-data rules** — ID numbers (with checksum validation), phone/landline, email, unified social credit codes, court & prosecutorial office names, names (context-aware), addresses, dates of birth
- **Consistent, restorable tokens** — `[姓名_1]`-style placeholders persist across requests and restarts (`map.json`), restored exactly on the way back
- **SSE streaming support** — handles token fragments split across network chunks
- **All protocols** — OpenAI (Responses/Chat) passthrough plus native adapters for Anthropic (Claude Code) and Google (Gemini); every mainstream model works per protocol (OpenAI-compatible: GPT/DeepSeek/Zhipu/Kimi/Qwen/Doubao/Groq/OpenRouter/local vLLM·Ollama…; Claude; Gemini) — see [dev doc §8.2](docs/开发文档.md#82-模型与服务商覆盖按协议归类)
- **Zero third-party dependencies** — pure Python standard library
- **Live dashboard** — real-time view of what was masked (placeholders only, never plaintext)
- **Extensible** — custom rules, custom word lists, new agents and document formats (see [Extending](docs/extending.md))

## Install

```bash
# Preferred:
pip install llm-sanitizer-gateway
llm-sanitizer start

# Source mode:
git clone https://github.com/JunyuZhan/llm-sanitizer.git
cd llm-sanitizer
python3 -m llm_sanitizer start
```

That's it. Two services come up:

- Gateway: `http://127.0.0.1:8790/v1` — point your agent's `base_url` here
- Dashboard: `http://127.0.0.1:8791` — open in a browser to watch masking in real time

Requirements: **Python 3.9+**, macOS or Linux. (Windows support is planned for v0.2.)

## Quick start

1. **Configure the upstream** (defaults to `https://api.openai.com/v1`):

   ```bash
   export LLM_SANITIZER_UPSTREAM="https://api.deepseek.com"      # your LLM provider
   export LLM_SANITIZER_KEY="sk-..."                              # your API key (optional if the agent already sends one)
   ```

2. **Start the gateway:**

   ```bash
   python3 -m llm_sanitizer start
   ```

3. **Point an agent at it** — any OpenAI-compatible client works by setting `base_url = http://127.0.0.1:8790/v1`. Step-by-step guides for Codex, WorkBuddy, and OpenClaw are in [Agent integration](docs/AGENTS.md).

4. **Verify it works:** send a test message like `申请人张三，电话 13912345678` from your agent, then open the dashboard — you should see new mask events appear within seconds.

Full walkthrough, configuration reference, upgrade & uninstall: [Quick start](docs/quickstart.md).

## How it works

| Stage | Data | Where it goes |
|---|---|---|
| Agent → gateway | raw request (conversation / file content) | in-memory only, masked then forwarded |
| Gateway → upstream | masked placeholder text | your configured LLM provider |
| Upstream → gateway | model response | restored locally, sent back |
| Gateway → dashboard/events | placeholders, categories, timestamps, paths | local JSONL, **no plaintext** |
| `map.json` | plaintext ↔ placeholder mapping | local disk, permissions `600` |

## Documentation

| Doc | Contents | Lang |
|---|---|---|
| [Quick start](docs/quickstart.md) | install, configure, integrate, verify, upgrade, uninstall | EN · [中文](docs/quickstart.zh-CN.md) |
| [需求文档](docs/需求文档.md) | product requirements, acceptance criteria, risks, roadmap | 中文 |
| [开发文档](docs/开发文档.md) | architecture, modules, ADRs, status matrix, testing | 中文 |
| [Security & trust](docs/SECURITY.md) | trust model, data flow, threat model, vulnerability reporting | EN · [中文](docs/SECURITY.zh-CN.md) |
| [Agent integration](docs/AGENTS.md) | Codex / WorkBuddy / OpenClaw setup | 中文 |
| [Extending](docs/extending.md) | custom rules, word lists, new formats, library API | EN · [中文](docs/extending.zh-CN.md) |
| [FAQ](docs/faq.md) | common questions & honest limitations | EN · [中文](docs/faq.zh-CN.md) |
| [LEGAL.md](docs/LEGAL.md) | lawyer / legal use cases & compliance notes | 中文 |

## Known limitations (be honest with yourself)

> Full numbered list in [PRD §9](docs/需求文档.md#9-已知限制与风险实测发现如实记录) (R1–R9); the most user-facing items are listed here without re-numbering.

- **WebSocket supported (v0.2)**: the gateway ships a transparent WebSocket proxy — text messages are masked/restored, binary and control frames pass through. Verify with a test message after integrating.
- **Recognition coverage**: regex rules cannot catch every name, alias, or abbreviation. High-sensitivity cases need custom word lists (v0.2) or local models.
- **Masking ≠ anonymization**: placeholders prevent plaintext leakage, but context ("defendant, male, 30, Shenzhen") can still re-identify individuals.
- **Restore is exact-match only**: if the model rewrites a placeholder, it cannot be restored.

Read [SECURITY.md](docs/SECURITY.md) before trusting this tool. **Core fact:** it is a man-in-the-middle gateway — it can read everything you send to the model. It runs only on your machine, listens only on `127.0.0.1`, is open-source and auditable, and stores mappings locally with `600` permissions. Trust it only after reading the code.

## Roadmap

| Version | Scope |
|---|---|
| **v0.1** (current) | HTTP gateway, Chinese rules, live dashboard, installer, docs, e2e tests; PyPI release |
| **v0.2 (in progress)** | ✅ WebSocket proxy, ✅ custom word lists; next: docx/xlsx/pdf format-preserving masking, Windows, one-click integration (FR-12), drag-drop file masking (FR-14), desktop shell |
| **v0.3** | multilingual rules (EN/JP), organization policy & audit export, rule marketplace |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: Chinese comments/docs preferred for this project; any change touching privacy handling **must** describe the data-flow impact in the PR.

## License

MIT — see [LICENSE](LICENSE).

**Disclaimer:** this project does not constitute legal advice. Whether case materials may be processed by third-party LLMs is governed by your organization's rules, professional confidentiality obligations, and applicable privacy regulations.
