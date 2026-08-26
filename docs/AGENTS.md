# Agent 接入指南

统一原理:把 Agent 的模型接口地址指向本地网关 `http://127.0.0.1:8790/v1`。网关负责脱敏与还原,对 Agent 透明。

## 0. 前置条件

```bash
# 方式一:发布后(推荐)
pip install llm-sanitizer-gateway
llm-sanitizer start

# 方式二:源码(当前)
cd "LLM Sanitizer"
python3 -m llm_sanitizer start
```

确认网关已监听:`curl -s http://127.0.0.1:8790/v1/models`(返回 401/JSON 均说明在运行)。

## 1. Codex(CLI / 桌面版)

编辑 `~/.codex/config.toml`(先备份):

```toml
[model_providers.llm-sanitizer]
name = "LLM Sanitizer"
base_url = "http://127.0.0.1:8790/v1"
env_key = "LLM_SANITIZER_KEY"
wire_api = "responses"

model_provider = "llm-sanitizer"
```

启动 Codex 前导出上游密钥:`export LLM_SANITIZER_KEY="你的上游API密钥"`(网关会原样转发)。

> 若希望网关统一管理密钥,可在网关环境变量配置 `LLM_SANITIZER_KEY`,此时 Agent 端密钥可任意填写。

**常见坑**:
- Codex 必须使用 `wire_api = "responses"` 且**未启用 WebSocket**,否则流量不走 HTTP 网关(见已知限制)。
- 桌面版 Codex 的对话消息可能不经 HTTP 网关(取决于版本与传输方式);接入后务必用测试消息验证。

## 2. WorkBuddy

WorkBuddy 支持 OpenAI 兼容的自定义模型:

1. 打开模型选择器 → "配置自定义模型 / Custom API"。
2. 接口地址:`http://127.0.0.1:8790/v1`
3. API Key:你的上游密钥(或任意值,若网关配置了统一 `LLM_SANITIZER_KEY`)。
4. 模型名:填你实际使用的模型 ID。

## 3. OpenClaw / 其他 OpenAI 兼容客户端

通用步骤:

1. 找到该客户端的模型提供方(Provider)配置。
2. Base URL / API 地址填:`http://127.0.0.1:8790/v1`
3. 协议选择 OpenAI 兼容(Responses 或 Chat Completions,视客户端而定)。
4. 重启客户端。

## 4. 验证是否生效(必做)

在对话中发送一条含测试信息(如"申请人张三,电话13912345678")的消息,然后打开看板 `http://127.0.0.1:8791`,应能看到新增脱敏事件(类别 `姓名`、`手机号`,占位符 `[姓名_1]`、`[手机号_1]`)。

**验证清单**:

- [ ] 网关 `curl http://127.0.0.1:8790/v1/models` 有响应
- [ ] Agent 的 base_url 指向 `http://127.0.0.1:8790/v1`
- [ ] 看板 `http://127.0.0.1:8791` 能打开
- [ ] 发送含测试隐私的消息后,看板 2 秒内出现脱敏事件
- [ ] 回复内容正常还原(无 `[姓名_1]` 残留;工具调用参数中的残留见需求文档 §9 R7)

## 5. 已知限制

- 走 WebSocket 通道的客户端在 v0.1 无法拦截(见 [SECURITY 文档](SECURITY.zh-CN.md))。
- 桌面版 Codex 的对话消息可能不经 HTTP 网关(取决于版本与传输方式);接入后请务必用测试消息验证。
- 工具调用参数中的占位符残留属 v0.1 已知缺口(风险 R7,见[需求文档](需求文档.md#9-已知限制与风险实测发现如实记录))。

## 6. 接入新 Agent(贡献指南)

**第一步:判断协议**。

- **OpenAI 兼容**(Responses / Chat Completions):零代码接入,`base_url` 指向网关即可,本文档补一节使用步骤即可贡献。
- **非 OpenAI 协议**(Anthropic Messages / Google generateContent 等):需要实现协议适配器,见[开发文档 §8.1](开发文档.md#81-新-agent-接入协议适配层adr-13)。

**贡献清单(按 PR 模板提交)**:

1. `config_manager` 注册条目:检测路径(如 `~/.codex/config.toml`)与配置格式;
2. 协议类型:OpenAI 直通 或 适配器;
3. 接入步骤 + 验证清单(照抄本文档 §4 模板,必做"测试消息 + 看板确认");
4. 已知限制如实标注(如桌面版走 WebSocket、协议字段差异)。

**验证模板(每新增一个 Agent 必须填写)**:

- [ ] 网关 `curl http://127.0.0.1:8790/v1/models` 有响应
- [ ] 发送含测试隐私消息后,看板 2 秒内出现脱敏事件
- [ ] 回复内容正常还原(无 `[姓名_1]` 残留)
- [ ] 已如实标注该 Agent 的已知限制
