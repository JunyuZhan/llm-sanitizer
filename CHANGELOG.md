# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **connect codex 迁移自愈(v0.5.2+ 审查修复)**:旧版(≤v0.3)一键接入把
  `model_provider` 根键误写入 `[model_providers.llm-sanitizer]` 表内,Codex
  实际未切换 provider。现在 `apply()` 能识别该坏配置:补根键(首个 `[table]`
  之前)、清理表内残留键、先备份可一键还原;`detect_agents()` 的 applied
  判断从子串匹配升级为"根键存在且指向 llm-sanitizer + 表存在",坏配置不再
  误报已接入。根级已声明其他 provider(如 openai)时接入会替换为
  llm-sanitizer(disconnect 可还原)。
- **CI 全量回归**:`test_e2e.py` 聚合漏掉 `test_port_probe.py`(11 项,覆盖
  端口预检与 v0.5.2 端口持久化),CI 此前只跑 109/120——已补齐聚合。
  Tests: +5(config_manager 迁移/替换/注释误判),125 total,all pass。

## [0.5.3] - 2026-08-27

### Added

- **桌面窗口一键模式**:后台已有服务(开机自启/手动 start)时,`llm-sanitizer desktop`
  直接打开看板窗口看数据——不重复起服务,关闭窗口不影响后台(launchd 托管)。
  空闲时才自起服务,关窗即停。窗口即"一键打开看数据、关窗即走"。
- Tests: +5(desktop 三态 + 关窗不停后台服务),129 total。

## [0.5.2] - 2026-08-27

### Added

- **端口选择持久化**:`start --port N` / `--dashboard-port N` 一次,端口写回
  `settings.json`(原子写 + 600),之后 `llm-sanitizer start`、开机自启
  (`install`)、`status`、`connect` 全部默认用新端口——换端口从此只需一次,
  不再每次手动带参。优先级:环境变量 > settings > 默认(环境变量保留运维/测试覆盖能力)。

### Fixed

- 测试修复:`threading.Event` 被全局替换为 FakeEvent 会破坏 `Thread._started`
  内部协议,导致 KeyboardInterrupt 泄漏、pytest 提前中止(5/11 收集项未执行、
  全量误报 113 而非 119)。改为给 `cmd_start` 提取 `_wait_forever()`,测试只
  patch 它,不再触碰 threading 内部。Tests: +3(端口持久化读写/环境变量覆盖/
  cmd_start 写回),119 total。

## [0.5.1] - 2026-08-27

### Fixed

- **`start` 端口占用友好处理(取代裸 traceback)**:启动前探测网关/看板端口归属
  (`gateway.probe_port`,依据 `Server: LLMSanitizer/…` 响应头前缀识别,
  跨版本稳定,能认出旧实例)。三种情形都给可操作中文提示:已在运行 →
  "无需重复启动,用 status 查看";被其他程序占用 → 给出换端口命令;空闲 → 正常启动。
  `desktop` 命令同样处理。
- **`start --port N` / `start --dashboard-port N`**:端口冲突时可换端口启动
  (之前参数不存在,冲突只能靠停掉别的程序)。
- 启动路径的 OSError 兜底:即便预检与绑定之间有竞态,也只打印友好提示而非 traceback。
- Tests: +5(`probe_port` 空闲/他服务/自家网关三态;`cmd_start` 已在运行/网关被占/
  看板被占/正常启动/显式端口五分支),113 total。
- 测试断言修正:LaunchAgent plist 命令路径接受连字符(`…/llm-sanitizer`,pip/pipx 脚本)
  与下划线(`python3 -m llm_sanitizer`,install.sh 兜底)两种形式——原断言只认下划线,
  在装有独立脚本的机器上误报。

## [Unreleased] — 0.6.0

### Added

- **English rules (v0.5 candidate, landed post-0.5.0)**: US SSN (`XXX-XX-XXXX`
  with strict structure check — area 001–899 excluding 666, non-zero group/
  serial) as new category `SSN`; international passport numbers via strong
  context (`Passport no./护照号/旅行证件` + format: `N1234567`,
  `NB12345678`, `AB123456`, `12345678X`) merged into `证件号`. Format-only
  patterns stay context-gated to avoid order-number false positives. Tests:
  +13 cases (hits + 7 FP samples). Categories now 16.

## [0.5.0] - 2026-08-27

### Added

- **Org policy** (`policy.json`, 600): `enforced_categories` (org-mandated on,
  overrides user), `blocked_categories` (forced off), `retention_days` (event
  retention, default 90); effective categories = (user ∪ enforced) − blocked.
- **Audit export**: `llm-sanitizer audit-export` → CSV (per-event) or
  `--json` (with cumulative summary); placeholder-only (no plaintext),
  `--since YYYY-MM-DD` filter, 600-perm atomic write; events now carry dates
  (`YYYY-MM-DD HH:MM:SS`) for day-level filtering; `read_all_events` merges
  the main file + rotated history; rotation now keeps 3 incremental archives
  (.1/.2/.3) instead of overwriting a single one — long-term audits survive;
  startup cleanup honors retention.
- **Desktop window**: `pip install llm-sanitizer-gateway[desktop]` +
  `llm-sanitizer desktop` opens the console in a native pywebview window
  (optional extra, ADR-1 core stays zero-dependency); window close stops the
  gateway/dashboard.
- **Standalone executable**: `packaging/llm_sanitizer.spec` + `build.py` —
  PyInstaller one-file build, verified on macOS (9.4 MB, all CLI commands
  work: help/status/mask/connect); signing/notarization steps documented.
- Console: settings page shows org-enforced categories (cannot be unchecked).
- **Desktop window packaged into the standalone executable**: spec uses
  `collect_all('webview')` + cocoa/gtk platform imports; verified on macOS —
  `desktop` opens the window, gateway/dashboard serve, no crash.
- **Rule-engine reliability fixes (found by scenario/fuzz verification)**:
  case numbers with half-width parens `(2026)` now matched; `户名`/`开户名`
  added as name context words (was the most common bank-doc field, unmasked);
  license plates after Chinese words (`车牌粤B12345`) now matched — lookbehind
  no longer excludes CJK (structure is unique, no new false positives: 广东的
  B类货物/该公司在A股上市/京津冀地区 all stay untouched).
- Reliability verification: 31-check scenario suite (15 categories in real
  contracts/judgments/bank docs, 8 false-positive samples, 14 edge inputs,
  200 fuzz strings, restore round-trip/fragment/multi-turn/restart/concurrent,
  category matrix) — all pass.
- Tests: +13 (policy merge/enforced/blocked/retention, audit CSV/JSON/since,
  read_all across rotated history, rotation keeps 3 archives, desktop hint,
  packaging artifacts; +5 rule cases) — 109 total, all pass.

## [0.4.2] - 2026-08-27

### Fixed (full-code review round)

- **Anthropic request-side `tool_use.input` (dict) now masked** — the same
  symmetric gap as the old OpenAI `arguments` P1: after the gateway restored
  tool-call arguments to plaintext, the client's next-turn echo passed them
  upstream unmasked. `input` dict/list (and `arguments` dict form) now go
  through `_mask_all_strings`; verified by e2e and reproduced-experiment.
- **Anthropic streaming `input_json_delta` restored** — streamed tool-call
  parameters (fragment-split JSON) now flow through the StreamRestorer;
  `_transform_event` promoted to a module-level function for testability.
- **Cumulative stats persisted (FR-5, reviewer-deferred)**: `stats.json`
  (atomic, 600) holds per-category counters — dashboard/`status` no longer
  regress past the 300-event tail or lose counts on rotation/restart.
  Verified live: 350 events after rotation → dashboard shows 350.
- Gateway class-structure fix found while refactoring: a module-level def
  inside the class body silently truncated `GatewayHandler` (lost methods,
  RemoteDisconnected on 403) — caught by the review round, restructured.
- Tests: +5 (Anthropic input masking, input_json_delta, stats persist /
  rotation / 600) — 96 total, all pass.

## [0.4.1] - 2026-08-27

### Fixed

- **OCR row-merge before masking**: tesseract splits Chinese into single-char
  blocks ("姓名:张三" → 姓/名/:/张/三), so context rules (names, addresses)
  never matched. Blocks are now merged per visual row (x-sorted, bbox union)
  before masking — verified on real tesseract 5.5 + chi_sim: id-card name /
  address / phone now all masked (was phone-only). Redaction covers the whole
  row (bbox union), text report stays readable.
- **`upgrade` prerelease hint**: on a dev/rc version with no newer stable,
  the message said "already latest" — now honestly says "prerelease, stable is X".
- Tests: +5 (merge reconstruction, multi-row preserved, merged context-rule
  hits, upgrade prerelease/stable hints) — 91 total, all pass.

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
