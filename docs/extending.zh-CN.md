# 扩展 LLM Sanitizer

四个扩展点,由易到难。[English](extending.md)

> **接口状态**:以下 API 是 v0.1 的目标契约。规则引擎(`masker.py`)随 v0.1 落地——见[模块与实现状态](../docs/开发文档.md#2-模块与实现状态)。本文内容以该模块存在为前提。

## 扩展点总览

| 层级 | 扩展什么 | 难度 | 位置 |
|---|---|---|---|
| 1 | 自定义规则(新的敏感类别) | 低 | 一条正则 + 一个测试文件 |
| 2 | 自定义词表(姓名、别名、机构) | 低 | 配置文件 / 词表文件(v0.2) |
| 3 | 接入新 Agent | 无(纯配置) | `docs/AGENTS.md` |
| 4 | 新文档格式处理器(docx/xlsx/pdf) | 中 | 格式处理器模块(v0.2) |

## 1. 添加自定义规则

规则是 (正则, 类别) 对,定义在 `masker.py` 中。引擎按顺序匹配,先命中者胜。

```python
# 目标接口(v0.1 落地)
from llm_sanitizer.masker import Masker, mask_text

m = Masker()
masked, _ = mask_text("联系 021-1234-5678 协商", m)
# → "联系 [座机号_1] 协商"
```

添加自己的规则,注册一条正则与类别即可:

```python
# 在 masker.py 的 RULES 列表中追加——示例:案号 "（2026）京01民初123号"
RULES.append(
    (
        re.compile(r"（\d{4}）[京沪粤][\u4e00-\u9fa5]+\d{1,4}民初\d+号"),
        "案号",
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

## 2. 自定义词表(v0.2)

正则无法推断的姓名、别名、机构简称,将由用户词表驱动——数据目录下的纯文本文件,每行一条。脱敏引擎在正则之前先检查词表条目。设计见[需求文档](../docs/需求文档.md#10-roadmap)。

## 3. 接入新 Agent

网关无需改动。任意 OpenAI 兼容客户端,把 base URL 指向网关即可:

```text
base_url = http://127.0.0.1:8790/v1
```

客户端若需指定协议,选 Responses API 或 Chat Completions(均支持)。想贡献某个 Agent 的接入步骤,在 [AGENTS.md](AGENTS.md) 加一节并发 PR。

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
