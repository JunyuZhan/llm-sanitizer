# LLM Sanitizer

[![CI](https://github.com/JunyuZhan/llm-sanitizer/actions/workflows/ci.yml/badge.svg)](https://github.com/JunyuZhan/llm-sanitizer/actions/workflows/ci.yml)

**本地 AI 流量隐私网关**。在 AI Agent(Codex、WorkBuddy、OpenClaw、Claude Code、Cline……)把数据发往云端大模型之前,自动把姓名、身份证号、手机号、地址、司法机关名称等敏感信息替换成 `[姓名_1]` 这类占位符;返回时精确还原,并用**实时看板**让你亲眼看到"什么被脱敏了"。

> 目标用户:律师、法务、以及所有把本地文档交给 AI Agent 处理、又担心隐私泄漏的人。

[🇬🇧 English README](README.md)

---

## 项目状态

> ⚠️ **文档先行开发中。** 本仓库当前交付了完整的文档体系和外围骨架(`config`、`events`、`gateway`、`dashboard`、`cli`),核心规则引擎(`masker.py`)、程序入口(`__main__.py`)、安装脚本与测试套件**正在补齐**——详见[模块与实现状态](docs/开发文档.md#2-模块与实现状态)。文档描述的是目标系统;上述模块落地后,快速开始命令即完全可用。欢迎参与贡献。

## 它解决什么问题

Agent 工具处理本地任务时会读取本地文件(Word、Excel、PDF……)并发送给云端模型。这些文件里的姓名、身份证号、司法机关名称等隐私数据,会在你毫无感知的情况下出网。LLM Sanitizer 在"出网前"加一道本地安检:

```
Agent → [本地网关:脱敏] → 云端(只看到 [姓名_1] 这类占位符)
Agent ← [本地网关:还原] ← 云端
        ↑
   实时看板:你看到每一步脱敏
```

## 特性

- **本地优先网关** — 仅监听 `127.0.0.1`,不设系统代理、不装证书、不劫持全局流量
- **中文敏感信息识别** — 身份证(带校验和验证)、手机/座机、邮箱、统一社会信用代码、司法机关名称、姓名(上下文感知)、地址、出生日期
- **一致可还原的占位符** — `[姓名_1]` 格式跨请求、跨重启保持一致(`map.json`),返回时精确还原
- **SSE 流式支持** — 处理被网络分片切碎的占位符 token
- **OpenAI 兼容** — 同时支持 Responses API 与 Chat Completions,JSON 与 SSE
- **零第三方依赖** — 纯 Python 标准库
- **实时看板** — 实时查看脱敏情况(只展示占位符,绝不展示明文)
- **可扩展** — 自定义规则、自定义词表、新 Agent 与新文档格式(见[扩展指南](docs/extending.md))

## 安装

> ⚠️ **当前源码尚不可运行**:`__main__.py` 与 `masker.py` 尚未落地,下面的源码命令当前会报 `No module named llm_sanitizer.__main__`,仅作为 v0.1 目标态参考。可运行版本随 v0.1 代码落地发布。

```bash
# 首选(发布后):
pip install llmsanitize
llm-sanitizer start

# 源码方式(目标态,随 v0.1 落地):
git clone https://github.com/JunyuZhan/llm-sanitizer.git
cd llm-sanitizer
python3 -m llm_sanitizer start
```

启动后得到两个服务:

- 网关:`http://127.0.0.1:8790/v1` —— 把 Agent 的 base_url 指向这里
- 看板:`http://127.0.0.1:8791` —— 浏览器打开,实时查看脱敏

环境要求:**Python 3.9+**,macOS 或 Linux(Windows 支持列入 v0.2)。

## 快速开始

1. **配置上游**(默认为 `https://api.openai.com/v1`):

   ```bash
   export LLM_SANITIZER_UPSTREAM="https://api.deepseek.com"   # 你的模型服务商
   export LLM_SANITIZER_KEY="sk-..."                          # 你的 API 密钥(Agent 已带密钥时可省略)
   ```

2. **启动网关:**

   ```bash
   python3 -m llm_sanitizer start
   ```

3. **接入 Agent** —— 任意 OpenAI 兼容客户端,把 `base_url` 设为 `http://127.0.0.1:8790/v1` 即可。Codex / WorkBuddy / OpenClaw 的详细步骤见 [Agent 接入指南](docs/AGENTS.md)。

4. **验证生效** —— 在 Agent 里发送一条测试消息(如"申请人张三,电话 13912345678"),打开看板,几秒内应看到新增脱敏事件。

完整操作、配置参考、升级与卸载:[快速开始](docs/quickstart.zh-CN.md)。

## 工作原理

| 阶段 | 数据 | 去向 |
|---|---|---|
| Agent → 网关 | 原始请求体(含对话/文件内容) | 仅在本机内存,脱敏后转发 |
| 网关 → 上游 | 脱敏后的占位符文本 | 你配置的上游 LLM |
| 上游 → 网关 | 模型响应 | 本机还原后回传 |
| 网关 → 看板/事件文件 | 占位符、类别、时间、请求路径 | 本机 JSONL,**不含明文** |
| `map.json` | 原文 ↔ 占位符映射 | 本机,权限 600 |

## 文档

| 文档 | 内容 | 语言 |
|---|---|---|
| [快速开始](docs/quickstart.zh-CN.md) | 安装、配置、接入、验证、升级、卸载 | 中文 · [EN](docs/quickstart.md) |
| [需求文档](docs/需求文档.md) | 产品需求、验收标准、风险、Roadmap | 中文 |
| [开发文档](docs/开发文档.md) | 架构、模块、ADR、实现状态矩阵、测试 | 中文 |
| [安全与信任](docs/SECURITY.zh-CN.md) | 信任模型、数据流、威胁模型、漏洞报告 | 中文 · [EN](docs/SECURITY.md) |
| [Agent 接入指南](docs/AGENTS.md) | Codex / WorkBuddy / OpenClaw 配置步骤 | 中文 |
| [扩展指南](docs/extending.zh-CN.md) | 自定义规则、词表、新格式、库 API | 中文 · [EN](docs/extending.md) |
| [常见问题](docs/faq.zh-CN.md) | 常见疑问与如实说明的限制 | 中文 · [EN](docs/faq.md) |
| [LEGAL.md](docs/LEGAL.md) | 律师/法务使用场景与合规提示 | 中文 |

## 已知限制(请如实面对)

> 完整编号见[需求文档 §9](docs/需求文档.md#9-已知限制与风险实测发现如实记录)(R1~R9);此处只列最影响使用的几条,编号不重复。

- **传输通道覆盖不全**:走 WebSocket 等非 HTTP 通道的客户端,v0.1 无法拦截。接入前请确认客户端使用 HTTP/SSE 传输。
- **识别覆盖有限**:正则规则无法覆盖所有姓名、别名、机构简称。高敏感场景需要自定义词表(v0.2)或本地模型。
- **脱敏 ≠ 匿名化**:占位符可防止明文外泄,但结合上下文("被告,男,30 岁,深圳")仍可能被推断。
- **还原只做精确回填**:模型改写占位符后无法还原。

使用前请先阅读 [SECURITY 文档](docs/SECURITY.zh-CN.md)。**核心事实**:这是一个"中间人"网关,能读取发给模型的所有内容——它只在你的本机运行、只监听 127.0.0.1、代码开源可审计、映射文件权限 600。信任它之前,请先读代码。

## Roadmap

| 版本 | 范围 |
|---|---|
| **v0.1**(当前) | HTTP 网关、中文规则、实时看板、安装脚本、文档、端到端测试;PyPI 发布 |
| **v0.2** | WebSocket 代理、docx/xlsx/pdf 保留格式脱敏、自定义词表、Windows 支持 |
| **v0.3** | 多语言规则(英文/日文)、组织策略与审计导出、规则贡献市场 |

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)(中文版 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md))。要点:本项目注释与文档以中文优先;任何涉及隐私处理逻辑的改动,**必须**在 PR 中说明数据流影响。

## License

MIT — 见 [LICENSE](LICENSE)。

**免责声明**:本项目不构成法律意见。是否可将案件材料交由第三方大模型处理,请遵守所在机构规定、律师保密义务及个人信息保护相关法规。
