# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-27

### Added

- **PDF format-preserving masking** (`formats.py`): decompress FlateDecode streams,
  rewrite `(…) Tj` / `[(…)…] TJ` text operators (byte-wise octal escaping — a real bug:
  Unicode-codepoint octal produced invalid 4+-digit escapes), recompress and update
  `/Length` (indirect-length objects skipped). Honest limits: split text fragments are
  not re-joined (context rules like names limited; format rules like phone/ID/email work),
  scanned PDFs (no text layer) unsupported. CLI mask/restore now handle .pdf.
- Tests: +2 (PDF round-trip with /Length update, indirect-length skip) — 77 total.
- **Image OCR masking** (`llm_sanitizer/ocr.py`, optional feature): engine abstraction with
  lazy imports keeps ADR-1 core zero-dependency — `pip install llm-sanitizer-gateway[ocr]`
  (pytesseract + Pillow) plus system tesseract (chi_sim for Chinese). Two modes: masked text
  report (default, restorable, layout-preserving by bbox row grouping) and redacted image
  (`--redact`, blacked-out boxes, irreversible). Core logic (`mask_blocks`/`render_text`/
  `redact_image`) are engine-free pure functions. Also: `_NAME_CTX` now includes the role word
  "姓名" — the highest-frequency OCR field (id-card "姓名 张三") was not being masked.
- Tests: +9 (mask blocks, mapping reuse, row-group layout, redaction pixels, real-engine smoke
  skipIf, CLI install hint, extension dispatch) — 86 total, all pass.

## [0.3.0] - 2026-08-27

### Added

- **Windows support**: data dir `%LOCALAPPDATA%\llm-sanitizer` (user-private ACLs replace
  the 600-perm semantics; `LLM_SANITIZER_HOME` still wins), `llm-sanitizer install` dispatches
  to schtasks ONLOGON (no admin) with pure-function arg builders, CI matrix + windows-latest
  (9 jobs), pyproject Windows classifier, FAQ/README updated.
- Tests: +2 (schtasks args, Windows data-dir logic) — 71 total.
- **Audit fixes**: P1 `connect codex` TOML root key placement (model_provider was
  landing inside the provider table — root keys must precede any `[table]`; now
  inserted before the first `[`, with tomllib assertion); P2 README status/roadmap
  aligned to v0.3, PRD header updated; P3 events.jsonl auto-rotation (5 MB → .1),
  dashboard by_category HTML-escaped, WS proxy connects upstream before replying
  101 (no dirty JSON on upstream failure), Windows uninstall checks schtasks rc,
  upgrade hint platform-dispatched. Tests: +4 (toml root key, event rotation/
  stats/tail) — 75 total, all pass.
- Release checklist: verify `llm-sanitizer install`/`--uninstall` on a real
  Windows host (schtasks /TR quoting) before shipping v0.3.0.

## [0.2.0] - 2026-08-27

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
- **Google Gemini protocol support**: `/v1beta` paths no longer stripped by forward_path
  (was a real bug — any `/v1beta/...` upstream 404'd); `candidates[].content.parts[].text`
  stream-restored in SSE with finishReason reset; request masking covers contents/systemInstruction.
  All three mainstream protocols now covered.
- Docs: protocol matrix (OpenAI/Anthropic/Gemini all v0.2 ✅) + provider/model coverage table
  grouped by protocol (per-protocol passthrough = every model in that family); AGENTS.md §3
  Gemini CLI; README feature line updated.
- Tests: +4 (Gemini JSON masking/restore, v1beta path regression, Gemini SSE chunk restore)
  — 64 total, all pass.
- **Multimodal text fragments masked**: `alt`/`filename`/`name` added to MASK_KEYS and
  (symmetrically) RESTORE_KEYS — image descriptions and attachment names no longer slip out.
- **Format-preserving masking for docx/xlsx** (`llm_sanitizer/formats.py`): rewrites only text
  nodes (`w:t`/`w:delText`/`t`) inside the ZIP's XML, escaping-aware, styles untouched; CLI
  `mask`/`restore` dispatch by extension; round-trip is byte-exact (verified). PDF deferred (pure
  stdlib text extraction unreliable).
- Tests: +5 (docx structure preserved + restore byte-exact, xlsx sharedStrings, is_zip_doc,
  non-text XML untouched) — 69 total, all pass.

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
