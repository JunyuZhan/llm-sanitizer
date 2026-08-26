# Extending LLM Sanitizer

Four extension points, from easiest to most involved. [中文版](extending.zh-CN.md)

> **Interface status:** the APIs below are the target contracts for v0.1. The rule engine (`masker.py`) is landing with v0.1 — see the [status matrix](../docs/开发文档.md#2-模块与实现状态). Everything here assumes that module exists.

## Extension point overview

| Level | What you extend | Effort | Where |
|---|---|---|---|
| 1 | Custom rules (new sensitive categories) | Low | one regex + one test file |
| 2 | Custom word lists (names, aliases, orgs) | Low | config / word-list file (v0.2) |
| 3 | New agent integration | None (config) | `docs/AGENTS.md` |
| 4 | New document format handler (docx/xlsx/pdf) | Medium | format handler module (v0.2) |

## 1. Add a custom rule

Rules live in `masker.py` as (regex, category) pairs. The engine walks them in order; the first match wins.

```python
# target interface (landing with v0.1)
from llm_sanitizer.masker import Masker, mask_text

m = Masker()
masked, _ = mask_text("联系 021-1234-5678 协商", m)
# → "联系 [座机号_1] 协商"
```

To add your own rule, register a regex and category:

```python
# in masker.py, RULES list — example: 案号 "（2026）京01民初123号"
RULES.append(
    (
        re.compile(r"（\d{4}）[京沪粤][\u4e00-\u9fa5]+\d{1,4}民初\d+号"),
        "案号",
    )
)
```

**Every rule change requires both test samples:**

```python
# hit sample  (must mask)
assert "（2026）京01民初123号" in mask_text(...)[0] is False

# false-positive sample (must NOT mask)
assert "（2026）京01民初123号" not in "...认为..."  # placeholder text stays
```

Rule quality rule: if you can't write a plausible false-positive test, the regex is probably too loose to merge.

## 2. Custom word lists (v0.2)

Names, aliases, and organization abbreviations that regexes can't infer will be driven by a user word list — a plain file in the data directory, one entry per line. The masking engine checks word-list entries before regex rules. Design is tracked in [需求文档](../docs/需求文档.md#10-roadmap).

## 3. Integrate a new agent

No gateway changes needed. Any OpenAI-compatible client works by pointing its base URL at the gateway:

```text
base_url = http://127.0.0.1:8790/v1
```

If the client needs a specific protocol, choose Responses API or Chat Completions (both supported). To contribute the steps for your favorite agent, open a PR adding a section to [AGENTS.md](AGENTS.md).

## 4. Document format handlers (v0.2)

Binary formats (docx/xlsx/pdf) need a three-stage pipeline:

```
format handler:  parse → text extraction → mask/restore → rebuild
```

The handler lives **outside** `masker.py`: it extracts text (which `mask_text`/`restore_text` can process), then rebuilds the document preserving layout. Contribution checklist for a new format:

1. `parse()` → text with stable anchors (so restore can find the right spans)
2. mask / restore via the public API
3. rebuild with original formatting
4. tests: a fixture document with known sensitive values, asserting no plaintext survives the round trip

## 5. Use the masking engine as a library

Independent of the gateway, `mask_text` / `restore_text` are plain functions you can import anywhere:

```python
from llm_sanitizer.masker import mask_text, restore_text

text = "申请人张三，电话 13912345678"
masked, m = mask_text(text)          # m.mapping: {"[姓名_1]": "张三", "[手机号_1]": "13912345678"}
restored = restore_text(masked, m.mapping)
assert restored == text
```

Persist `m.mapping` (e.g. to `map.json`) to restore later, across processes and restarts.

## Engineering rules for extensions

- Any change touching masking logic **must** include hit and false-positive test samples.
- Privacy-relevant changes **must** describe the data-flow impact in the PR (see [CONTRIBUTING](../CONTRIBUTING.md)).
- Run `python3 tests/test_e2e.py` before pushing.
- Chinese comments and docs preferred.
