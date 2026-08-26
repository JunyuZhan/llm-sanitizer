# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (docs-first milestone)

- Complete documentation suite restructured for open-source consumption:
  - Bilingual README (`README.md` / `README.zh-CN.md`) with badges, status disclosure, and doc map
  - New `docs/quickstart.md` (EN + zh-CN): install, configure, verify, upgrade, uninstall
  - New `docs/faq.md` (EN + zh-CN): honest limitations, data handling, security Q&A
  - New `docs/extending.md` (EN + zh-CN): four extension points and their contracts
  - `docs/SECURITY.md` (EN) + `docs/SECURITY.zh-CN.md`: threat model, vulnerability reporting
  - `docs/需求文档.md` / `docs/开发文档.md`: acceptance criteria, status matrix, ADRs, known-defect register (D1–D6)
- Community scaffolding: `CHANGELOG.md`, `CONTRIBUTING.md` (+ zh-CN), `CODE_OF_CONDUCT.md`,
  issue templates and PR template with privacy data-flow requirement
- Project status policy: docs-first development, core modules tracked in the status matrix

### Planned for v0.1.0

- `llm_sanitizer/masker.py` — Chinese-sensitive-data rule engine (the missing core)
- `llm_sanitizer/__main__.py` — `python3 -m llm_sanitizer` entry point
- `install.sh` — launchd / systemd installer (pip install becomes the primary path)
- `tests/` — unit + e2e suite (`mock_upstream.py`, `test_e2e.py`) covering AC-1…AC-8
- `pyproject.toml` — PyPI packaging; `pip install llm-sanitizer` + `llm-sanitizer start`
- Fix known defects D1–D6 (see `docs/开发文档.md §9`)
