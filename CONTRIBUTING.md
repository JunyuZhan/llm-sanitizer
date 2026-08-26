# Contributing to LLM Sanitizer

[中文版](CONTRIBUTING.zh-CN.md)

Thanks for your interest! This project is a **privacy tool** — the bar for care and transparency is higher than for a typical utility. Please read all of this before opening a PR.

## Code of conduct

Everyone is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Project status & where to help

The project is in **docs-first development** for v0.1. The most useful contributions right now:

1. **Core modules (v0.1)**: `masker.py` (rule engine), `__main__.py`, `install.sh`, `tests/`, `pyproject.toml` — see the [status matrix](docs/开发文档.md#2-模块与实现状态).
2. **Known defects**: D1–D6 in [开发文档 §9](docs/开发文档.md#9-已知实现缺陷v01-必须修复).
3. **Documentation**: English translations, FAQ entries, agent integration guides.

## Development setup

```bash
git clone https://github.com/JunyuZhan/llm-sanitizer.git
cd llm-sanitizer
python3 -m llm_sanitizer start     # requires Python 3.9+, no third-party deps
python3 tests/test_e2e.py          # run tests before pushing
```

## Rules for every contribution

### Privacy changes must document data-flow impact

Any change that touches masking, restoring, event logging, or mapping storage **must** describe in the PR:

- what data is read, where it goes, and where it is persisted;
- whether any new plaintext is stored on disk (and its permissions);
- any new external call the gateway makes.

If you cannot describe the data flow of your change, it will not be merged.

### Rule changes require hit + false-positive tests

Every new or modified masking rule **must** include:

- a **hit sample** — text that must be masked;
- a **false-positive sample** — similar-looking text that must NOT be masked.

If you can't write a plausible false-positive sample, the rule is too loose. This is a merge gate, not a suggestion.

### Language policy

- Chinese is the primary language for code comments and the deep docs (`需求文档`, `开发文档`, `AGENTS`, `LEGAL`).
- User-facing entry docs (`README`, `quickstart`, `SECURITY`, `FAQ`, `extending`) are maintained **bilingual**: EN and zh-CN versions must stay in sync in the same PR.
- Commit messages: any language, but be descriptive.

### Tests must pass

```bash
python3 tests/test_e2e.py
```

New functionality needs tests. Rule changes need the hit/false-positive samples above.

## Workflow

1. Open an issue describing the change, or pick an open one (label `good first issue` is a good start).
2. Fork, create a branch, make changes.
3. Run tests, update docs if behavior changed.
4. Open a PR against `main` referencing the issue; fill in the PR template (including the data-flow section for privacy changes).
5. CI (once configured) must pass; a maintainer will review.

## Release notes

- Version bumps follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
- Update [CHANGELOG.md](CHANGELOG.md) in the same PR (`Unreleased` section).

## Questions

Open a discussion or issue — see the [FAQ](docs/faq.md) first, it may already be answered.
