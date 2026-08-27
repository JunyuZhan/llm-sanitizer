# FAQ

Honest answers to common questions. [中文版](faq.zh-CN.md)

## General

### Why not intercept all traffic like a system-level proxy?
Scope is a deliberate security decision. A system proxy is invasive (touches every app, may require certificates) and becomes a much bigger attack surface. LLM Sanitizer only affects clients that explicitly point their `base_url` at the gateway — nothing else changes.

### Is it a firewall? Can it block specific requests?
No. It is a **masking gateway**, not a firewall: it rewrites content, it does not allow/deny requests. Blocking rules are not a v0.1 goal.

### Does it work with any LLM provider?
Any provider exposing an OpenAI-compatible API (Responses or Chat Completions): OpenAI, DeepSeek, Moonshot, local proxies, etc. Configure `LLM_SANITIZER_UPSTREAM` accordingly.

## Coverage & limits

### Why can't it intercept WebSocket traffic?
v0.1 only speaks HTTP/SSE. Some clients (especially desktop apps) use WebSocket for streaming. Intercepting WebSocket requires a separate proxy implementation, planned for v0.2. Before integrating, confirm your client uses HTTP/SSE.

### Will the model be confused by placeholders like `[姓名_1]`?
Most models handle them fine, since placeholders are self-describing. In rare cases a model may quote or rewrite a placeholder — in that case it can't be restored (exact-match only), and the placeholder simply stays in the response. It never leaks plaintext back upstream.

### Could the model guess the plaintext from `[姓名_1]`?
The placeholder format is guessable in principle, but the model never receives the plaintext — guessing it would require information the model simply doesn't have. However, context can leak: *"被告，男，30 岁，深圳"* narrows identity regardless of masking. That's the masking ≠ anonymization limit.

### How do I know masking actually covers my documents?
Test it: send a message with deliberately inserted sample data, then check the dashboard. For real coverage, add names/aliases/abbreviations the regexes can't catch to the **custom word list** (the console's "Custom word list" panel or `~/.llm-sanitizer/wordlist.txt`; entries take priority over built-in rules).

### Can I choose which categories are masked?
Yes (FR-15). Each built-in rule has a category id you can enable/disable in the console, via environment/config, or per-file with `mask --categories`. Presets: high-sensitivity (all on) / office (names, phones, email, company names, bank accounts, address) / custom. **Default is everything on.** Disabling a category means that kind of data goes to the cloud in plaintext — the UI warns you before you confirm, and the dashboard always shows "N/15 categories active".

### Are API keys and passwords masked too?
Yes — they are the highest-priority category for an LLM traffic gateway. The `密钥/令牌` rule catches common secret patterns (`sk-...`, `ghp_...`) and fields named password/token, and is **on by default**. It protects you when an agent processes a config file, `.env`, or any document that happens to contain credentials.

## Data & restore

### What is `map.json` and what happens if I lose it?
`map.json` (in `~/.llm-sanitizer/`) holds the plaintext↔placeholder mapping. It's written after every request so tokens survive restarts. If you delete it, already-sent placeholders can no longer be restored — treat it as sensitive data.

### What happens if `map.json` is mixed between CLI and gateway?
CLI masking (`mask`/`restore`) uses its **own** mapping with independent counters. A `[姓名_1]` from the CLI and one from the gateway can point to different people. Never merge them. Use one mapping source per workflow.

### Does the gateway keep my plaintext around?
Plaintext exists only: (1) in memory while masking a request, (2) in `map.json` on your disk (permissions 600), and (3) in restored responses going back to your agent. Events and logs store placeholders only.

## Security

### Can it defend against prompt injection?
No — and nothing that rewrites text can. If a prompt injection causes the model to echo masked data, the model only has placeholder text to echo. But injection can still manipulate the *agent's behavior*. Use gateway masking as one layer, not the only control.

### Is the gateway itself a security risk?
Yes, by design: it's a man-in-the-middle. Mitigations: loopback-only binding, zero dependencies, open-source code, `600`-permission mapping file. It cannot defend against full local compromise (malware). See [SECURITY.md](SECURITY.md).

### How do I verify the installed code is the audited code?
Pin the version you use, and diff/checksum your checkout against a release tag. (Version-pinning automation is on the roadmap.)

## Performance & platform

### Will the gateway slow down my agent noticeably?
Masking is regex + dictionary lookups over text fields; for typical documents it's milliseconds per request. Streaming adds a small buffer for restore. No network detour — traffic goes to the same upstream you'd use anyway.

### Does it support Windows?
**Yes, since v0.3.** `pip install llm-sanitizer-gateway` works on all three platforms. Data lives in `%LOCALAPPDATA%\llm-sanitizer` (user-private ACLs replace the 600-perm semantics); auto-start via `llm-sanitizer install` (schtasks ONLOGON, no admin).

### How do I upgrade?
`pip install --upgrade llm-sanitizer-gateway` is all it takes; if auto-start is installed, also run `./install.sh --uninstall && ./install.sh` to restart the service. Or run `llm-sanitizer upgrade` to check the latest version and get instructions (`start` also checks in the background). Upgrades never lose mappings or stats — the `map.json` token format is stable, so old mappings still restore after upgrading.

### Does it support English / Japanese documents?
v0.1 ships Chinese rules only. Multilingual rules (EN/JP) are planned for v0.3.

## Compliance

### Can I use this to process case materials with a cloud LLM?
That depends on your organization's rules, professional confidentiality obligations, and applicable privacy law. The gateway reduces the risk of *plaintext* leaking; it does not remove it entirely, and this project is not legal advice. See [LEGAL.md](LEGAL.md).
