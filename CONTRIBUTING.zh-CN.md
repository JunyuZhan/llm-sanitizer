# 为 LLM Sanitizer 贡献

[English](CONTRIBUTING.md)

感谢你的关注!这是一个**隐私工具**——对严谨与透明的要求高于一般工具。提 PR 前请通读本文。

## 行为准则

所有参与者须遵守[行为准则](CODE_OF_CONDUCT.md)。

## 项目状态与可贡献方向

项目处于 v0.1 **文档先行**阶段。当前最有价值的贡献:

1. **核心模块(v0.1)**:`masker.py`(规则引擎)、`__main__.py`、`install.sh`、`tests/`、`pyproject.toml`——见[模块与实现状态](docs/开发文档.md#2-模块与实现状态)。
2. **已知缺陷**:[开发文档 §9](docs/开发文档.md#9-已知实现缺陷v01-必须修复) 的 D1~D6。
3. **文档**:英文翻译、FAQ 条目、Agent 接入指南。

## 开发环境

```bash
git clone https://github.com/JunyuZhan/llm-sanitizer.git
cd llm-sanitizer
python3 -m llm_sanitizer start     # 需 Python 3.9+,无第三方依赖
python3 tests/test_e2e.py          # 提交前运行测试
```

## 每项贡献的硬性要求

### 隐私改动必须说明数据流影响

任何涉及脱敏、还原、事件日志、映射存储的改动,**必须**在 PR 中说明:

- 读取了哪些数据、流向何处、持久化在哪里;
- 是否新增了落盘的明文(及其权限);
- 网关是否新增任何外部调用。

如果你的改动说不清数据流,不会被合并。

### 规则改动必须附命中 + 误报样例

每条新增/修改的脱敏规则**必须**提供:

- **命中样例** —— 必须被脱敏的文本;
- **误报样例** —— 形似但绝不能脱敏的文本。

写不出合理的误报样例,说明规则过宽。这是合并门禁,不是建议。

### 语言规范

- 代码注释与深度文档(`需求文档`、`开发文档`、`AGENTS`、`LEGAL`)以**中文**为主。
- 面向用户的入口文档(`README`、`quickstart`、`SECURITY`、`FAQ`、`extending`)**双语维护**:EN 与 zh-CN 版本必须在同一 PR 内保持同步。
- Commit message 语言不限,但要有描述性。

### 测试必须通过

```bash
python3 tests/test_e2e.py
```

新功能需要测试;规则改动需要上面的命中/误报样例。

## 工作流

1. 先开 issue 描述改动,或认领一个开放 issue(`good first issue` 标签是好的起点)。
2. Fork、建分支、做改动。
3. 跑测试;行为有变化则同步更新文档。
4. 向 `main` 开 PR 并引用 issue;按 PR 模板填写(隐私改动含数据流说明)。
5. CI(配置后)必须通过,维护者 review。

## 发布说明

- 版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。
- 同一 PR 内更新 [CHANGELOG.md](CHANGELOG.md)(`Unreleased` 节)。

## 问题

开 discussion 或 issue——先看 [FAQ](docs/faq.zh-CN.md),可能已有答案。
