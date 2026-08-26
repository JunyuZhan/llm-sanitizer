# 扩展 LLM Sanitizer

四个扩展点,由易到难。[English](extending.md)

> **接口状态**:以下 API 是 v0.1 的目标契约。规则引擎(`masker.py`)随 v0.1 落地——见[模块与实现状态](../docs/开发文档.md#2-模块与实现状态)。本文内容以该模块存在为前提。

## 扩展点总览

| 层级 | 扩展什么 | 难度 | 位置 |
|---|---|---|---|
| 1 | 自定义规则(新的敏感类别) | 低 | 一条正则 + 一个测试文件 |
| 2 | 自定义词表(姓名、别名、机构) | 低 | `wordlist.txt` / 控制台(已实现) |
| 3 | **新 Agent / 新协议** | 中 | 适配器 + 注册表条目(见下) |
| 4 | 新文档格式处理器(docx/xlsx 已实现;pdf 评估中) | 中 | `formats.py` |

## 1. 添加自定义规则

规则是 `(正则, 类别id, 类别名)` 三元组,定义在 `masker.py` 中——**每条规则携带唯一类别 id**,用户可单独启用/停用(见 FR-15)。引擎按顺序只匹配启用的规则,先命中者胜。

```python
# 目标接口(v0.1 落地)
from llm_sanitizer.masker import Masker, mask_text

m = Masker()
masked, _ = mask_text("联系 021-1234-5678 协商", m)
# → "联系 [座机号_1] 协商"
```

添加自己的规则,注册一条正则与类别即可:

```python
# 在 masker.py 的 RULES 列表中追加——示例:证据编号 "证1-2026-001"(案号已是内置类别)
RULES.append(
    (
        re.compile(r"证\d{1,3}-\d{4}-\d{3,5}"),
        "evidence_no",   # 唯一类别 id(看板与类别开关中展示)
        "证据编号",      # 人类可读的类别名
    )
)
```

**每条规则都必须同时提供两个测试样例:**

```python
# 命中样例(必须脱敏)
assert "（2026）京01民初123号" in mask_text(...)[0] is False

# 误报样例(必须不脱敏)
assert "（2026）京01民初123号" not in "...认为..."  # 占位符文本保持原样
```

规则质量标准:如果写不出合理的误报测试,说明正则过宽,不应合并。

## 2. 自定义敏感词表(已实现,v0.2)

正则无法推断的姓名、别名、机构简称,由用户词表驱动——数据目录下 `wordlist.txt`,每行一个词:

```text
# 每行一个词,可 `词` 或 `词|类别`(默认类别「自定义词表」)
张三丰|姓名
某某律师事务所|公司名称
```

- 词表条目**优先于**内置规则(重叠时词表胜);
- 词须独立成词(前后非 CJK/字母/数字),防止子串误伤(如词"张三"不匹配"张三丰");
- 维护途径:控制台"自定义敏感词表"区、`llm-sanitizer mask --wordlist 文件`,或直接编辑 `~/.llm-sanitizer/wordlist.txt`(保存后重启网关生效)。

引擎实现:`Masker(wordlist=[(词, 类别), ...])`;条目映射为标准 token,还原机制与内置规则一致。

## 3. 接入新 Agent

**先判断协议**——Agent 支持由协议绑定,而非"名字":

- **OpenAI 兼容客户端**(Codex、WorkBuddy、Cline、OpenClaw 及任意走 Responses / Chat Completions 的工具):零代码。把 base URL 指向网关:

  ```text
  base_url = http://127.0.0.1:8790/v1
  ```

  想贡献某客户端的接入步骤,在 [AGENTS.md](AGENTS.md) 加一节并发 PR。

- **非 OpenAI 协议**(Claude Code → Anthropic Messages、Gemini CLI → Google generateContent):请求结构完全不同(`content` 是数组、`system` 在顶层、`contents/parts` 嵌套)——按 OpenAI 字段名脱敏会漏检或失败,需要**适配器**:

  ```python
  # 目标接口(adapters/base.py)
  class Adapter:
      def parse_request(self, raw: dict) -> Message: ...
      def extract_text_fields(self, msg: Message) -> list[str]: ...
      def rebuild_request(self, msg: Message, masked: list[str]) -> dict: ...
      def restore_response(self, raw: dict) -> dict: ...
  ```

  新适配器贡献清单:
  1. 按上述接口实现 `adapters/<name>.py`;
  2. 在 `adapters/registry.py` 注册(按路径 / 协议头路由);
  3. 测试:一个含已知敏感值的样例请求,断言上游只收到占位符、客户端收到还原文本;
  4. 在[开发文档 §8.1](../docs/开发文档.md#81-新-agent-接入协议适配层adr-13) 的协议支持矩阵补一行。

核心引擎保持协议无关——**新增 Agent = 注册表条目 + 至多一个适配器**。

## 4. 文档格式处理器(v0.2)

二进制格式(docx/xlsx/pdf)需要三阶段流水线:

```
格式处理器:  解析 → 文本提取 → 脱敏/还原 → 重建
```

处理器放在 `masker.py` **之外**:它负责提取文本(交给 `mask_text`/`restore_text` 处理),再按原版式重建文档。新格式的贡献清单:

1. `parse()` → 带稳定锚点的文本(还原时能定位回正确的区间)
2. 通过公开 API 脱敏 / 还原
3. 按原格式重建
4. 测试:一个含已知敏感值的样例文档,断言往返后无明文残留

## 5. 把脱敏引擎当库用

与网关无关,`mask_text` / `restore_text` 是可在任何地方导入的普通函数:

```python
from llm_sanitizer.masker import mask_text, restore_text

text = "申请人张三，电话 13912345678"
masked, m = mask_text(text)          # m.mapping: {"[姓名_1]": "张三", "[手机号_1]": "13912345678"}
restored = restore_text(masked, m.mapping)
assert restored == text
```

把 `m.mapping` 持久化(如写入 `map.json`),即可跨进程、跨重启还原。

## 扩展的工程规范

- 任何涉及脱敏逻辑的改动,**必须**附命中与误报测试样例。
- 涉及隐私的改动,**必须**在 PR 中说明数据流影响(见 [CONTRIBUTING](../CONTRIBUTING.zh-CN.md))。
- 提交前运行 `python3 tests/test_e2e.py`。
- 注释与文档以中文优先。
