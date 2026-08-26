# 快速开始

大约五分钟,从零到"我的 Agent 流量已脱敏"。

[English](quickstart.md)

## 1. 前置条件

- **Python 3.9+**(无需安装任何第三方包)
- macOS 或 Linux
- 你的 Agent 所用模型服务商的账号与密钥

## 2. 安装

两种方式。**PyPI 包发布后(属于 v0.1 里程碑),优先用 pip:**

```bash
pip install llm-sanitizer
llm-sanitizer start
```

**在此之前,请用源码方式运行:**

```bash
git clone https://github.com/JunyuZhan/llm-sanitizer.git
cd llm-sanitizer
python3 -m llm_sanitizer start
```

> 还没有?核心模块正随 v0.1 落地——见[项目状态](../README.zh-CN.md#项目状态)与[模块与实现状态](../docs/开发文档.md#2-模块与实现状态)。

## 3. 配置

全部通过环境变量配置:

| 变量 | 默认值 | 作用 |
|---|---|---|
| `LLM_SANITIZER_UPSTREAM` | `https://api.openai.com/v1` | 上游模型 base URL。OpenAI 风格(base 带 `/v1`)与 DeepSeek 风格(不带)均可 |
| `LLM_SANITIZER_KEY` | *(空)* | 网关转发给上游的 API 密钥。Agent 自带 `Authorization` 头时可省略 |
| `LLM_SANITIZER_PORT` | `8790` | 网关端口(仅监听 `127.0.0.1`) |
| `LLM_SANITIZER_DASHBOARD_PORT` | `8791` | 看板端口 |
| `LLM_SANITIZER_HOME` | `~/.llm-sanitizer` | 数据目录(`map.json`、`events.jsonl`、日志) |

```bash
export LLM_SANITIZER_UPSTREAM="https://api.deepseek.com"
export LLM_SANITIZER_KEY="sk-你的密钥"
python3 -m llm_sanitizer start
```

启动后应看到:

```
[llm-sanitizer] 网关  http://127.0.0.1:8790/v1
[llm-sanitizer] 看板  http://127.0.0.1:8791
[llm-sanitizer] 上游  https://api.deepseek.com
```

## 4. 把 Agent 指向网关

统一模式:**把 Agent 的 base URL 设为 `http://127.0.0.1:8790/v1`**,任意 OpenAI 兼容客户端即可。

Codex / WorkBuddy / OpenClaw 的分步配置见 [Agent 接入指南](AGENTS.md)。

## 5. 验证确实生效

1. 在 Agent 里发一条测试消息,例如*"申请人张三,电话 13912345678"*。
2. 打开看板 `http://127.0.0.1:8791`。
3. 约 2 秒内应看到新增脱敏事件:类别 `姓名`、`手机号`,占位符 `[姓名_1]`、`[手机号_1]`。

看不到事件?见[故障排查](#7-故障排查)。

## 6. 日常使用与 CLI

| 命令 | 作用 |
|---|---|
| `python3 -m llm_sanitizer start` | 启动网关 + 看板(前台) |
| `python3 -m llm_sanitizer status` | 查看端口状态、上游、累计统计 |
| `python3 -m llm_sanitizer mask <文件>` | 不经过网关,对单个文本文件脱敏(CSV/JSON/SQL/代码……) |
| `python3 -m llm_sanitizer restore <文件> --map <map.json>` | 用映射文件还原已脱敏文件 |

**看板**展示:累计脱敏数、按类别分布、最近脱敏事件(只含占位符,绝不展示明文)、最近请求记录。

给律师的建议:可以先在本机对文件脱敏,再把脱敏版交给 Agent——见 [LEGAL.md](LEGAL.md)。注意:CLI 脱敏使用独立映射,不要与网关映射混用(见 [FAQ](faq.zh-CN.md#mapjson-在-cli-与网关之间混用会怎样))。

## 7. 故障排查

| 现象 | 可能原因 / 处理 |
|---|---|
| `No module named llm_sanitizer` | 未在仓库根目录运行,或核心模块尚未合并(v0.1 进行中)——见项目状态 |
| 看板没有事件 | Agent 实际没有走网关:检查 base_url;部分桌面 App 走 WebSocket 绕过 HTTP(已知限制 R1) |
| `upstream unreachable` | `LLM_SANITIZER_UPSTREAM` 配错或网络不通 |
| 上游返回 `401` | `LLM_SANITIZER_KEY` 缺失或错误;或 Agent 自带的密钥未被转发 |
| 响应里残留 `[地址_1]` 这类占位符 | 工具调用参数还原是 v0.1 已知缺口(见[开发文档](../docs/开发文档.md)) |

## 8. 升级与卸载

```bash
# 升级(源码安装)
cd llm-sanitizer && git pull

# 卸载(停服务、删配置与数据)
./install.sh --uninstall      # 或:python3 -m llm_sanitizer install --uninstall
rm -rf ~/.llm-sanitizer       # 映射 + 事件——map.json 等同敏感数据,谨慎!
```

随后把 Agent 的 base_url 改回原服务商。

**在把真实文档交给这个工具之前,请先读 [SECURITY 文档](SECURITY.zh-CN.md)。**
