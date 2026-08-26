# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 0.2.0

### Added

- **WebSocket transparent proxy** (`llm_sanitizer/websocket.py`): frame codec (masking, extended
  lengths, control frames, fragmentation), upstream handshake over ws/wss/http/https, bidirectional
  relay with text masking/restoration; binary frames (e.g. audio) and ping/pong/close pass through.
  Closes the R1 transport-coverage gap.
- **Custom sensitive word lists**: `~/.llm-sanitizer/wordlist.txt` (one word per line, optional
  `词|类别`); entries take priority over built-in rules, independent-word matching avoids substring
  false hits; maintained via CLI `mask --wordlist`, console panel and `POST /api/wordlist`.
- Console: custom word list panel (view/edit, 600-perm persistence, token-protected).
- **One-click agent integration (FR-12)**: `config_manager` full backup/apply/restore — Codex
  config.toml rewritten text-level (no tomllib dependency, Python 3.9 safe), original content
  preserved, backup with 600 perms, idempotent apply, restore returns exact original; wired as
  CLI `connect`/`disconnect`, console buttons (apply/restore with confirm), protected endpoints
  `POST /api/agents/apply|restore` (X-Local-Token).
- Tests: +11 cases (config_manager unit: detect/apply/backup/idempotent/restore/permissions;
  console apply 403 + round-trip) — 55 total, all pass.
- **Anthropic Messages protocol support (Claude Code)**: `anthropic-version` header
  whitelisted; API key injected as `x-api-key` for anthropic.com upstreams (Bearer otherwise,
  pure helper `auth_headers`); SSE `content_block_delta`/text_delta stream-restored with
  `message_stop` reset; response `tool_use.input` (arbitrary JSON) fully restored.
- Tests: +5 (Anthropic: upstream placeholders-only, text+tool_use.input restore, header
  forwarding, auth_headers matrix, SSE chunk restore) — 60 total, all pass.

## [0.1.0] - 2026-08-27

### Added

- Complete documentation suite restructured for open-source consumption:
  - Bilingual README (`README.md` / `README.zh-CN.md`) with badges, status disclosure, and doc map
  - `docs/quickstart.md` (EN + zh-CN): install, configure, verify, upgrade, uninstall
  - `docs/faq.md` (EN + zh-CN): honest limitations, data handling, security Q&A
  - `docs/extending.md` (EN + zh-CN): four extension points and their contracts
  - `docs/SECURITY.md` (EN) + `docs/SECURITY.zh-CN.md`: threat model, vulnerability reporting
  - `docs/需求文档.md` / `docs/开发文档.md`: acceptance criteria, status matrix, ADRs, defect register
- Community scaffolding: `CONTRIBUTING.md` (+ zh-CN), `CODE_OF_CONDUCT.md`, issue/PR templates
- `llm_sanitizer/masker.py` — 15-category rule engine (checksum/Luhn validation, context rules,
  category toggle, atomic 600-perm persistence)
- `llm_sanitizer/__main__.py` — `python3 -m llm_sanitizer` entry point
- `install.sh` — launchd / systemd auto-start installer with clean `--uninstall`
- `tests/` — 29 cases (unit + CLI + e2e) covering AC-1…AC-9
- `pyproject.toml` — PyPI packaging; published as `llm-sanitizer-gateway`, command stays `llm-sanitizer`
- CI (GitHub Actions: ubuntu+macos × py3.9/3.11/3.13)
- Dashboard upgraded to console: onboarding guide, settings form, category presets,
  protected write API (Host/Origin validation + local token)
- `llm-sanitizer upgrade` command + background update check (disable with
  `LLM_SANITIZER_CHECK_UPDATE=0`)
- `llm_sanitizer/config_manager.py` — agent detection (read-only, v0.1)

### Fixed

- All known defects D1–D8 (imports, restore fallback, tool-call arguments restore,
  map.json write lock, dashboard live dot, connection leak, 600 perms, global state)
- Second-round review: request-side list/tool-arguments masking gaps, Python 3.9
  annotation compatibility, 644 permission window, restore race snapshot,
  colon-separated names, launchd ProgramArguments, dashboard XSS escaping,
  ID `x` case round-trip, dashboard Host validation, events tail read,
  SSE `content_part.delta` compatibility, query-string stripped from events

### Security

- Gateway and dashboard validate `Host` header (loopback only) and reject
  cross-origin `Origin` (DNS-rebinding mitigation); write endpoints require a
  local token
- All sensitive files (`map.json`, `settings.json`, `events.jsonl`, CLI `--map`)
  persist atomically with `chmod 600`
