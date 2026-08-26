# Security & Trust Model

[中文版](SECURITY.zh-CN.md)

## 1. Positioning statement (read this first)

**LLM Sanitizer is a man-in-the-middle gateway.** It can technically read, modify, and forward everything you send to the model. That is its purpose — and its risk. Before using it, read the source code and confirm it matches your trust expectations.

## 2. Data flow

| Stage | Data | Destination |
|---|---|---|
| Agent → gateway | raw request body (conversation / file content) | in-memory only on this machine, masked before forwarding |
| Gateway → upstream | masked placeholder text | your configured LLM provider (e.g. DeepSeek) |
| Upstream → gateway | model response | restored locally, sent back to the agent |
| Gateway → dashboard / events file | placeholders, category, timestamp, request path | local JSONL, **no plaintext** |
| `map.json` | plaintext ↔ placeholder mapping | local disk, permissions `600` |

## 3. Security boundaries

- Listens on `127.0.0.1` **only** — unreachable from the network.
- Does **not** modify the system proxy, install certificates, or intercept non-agent traffic.
- Affects **only** clients configured with `base_url = http://127.0.0.1:8790/v1`.
- **Zero third-party dependencies** (pure Python standard library) — low supply-chain risk.
- Open source; audits welcome.

## 4. Storage & permissions

- `~/.llm-sanitizer/map.json` — plaintext↔placeholder mapping. **This is as sensitive as the plaintext itself.** Never share, upload, or commit it.
- `~/.llm-sanitizer/events.jsonl` — mask events (placeholder / category / time / request path), **no plaintext**; drives the dashboard.
- Logs — timestamps, paths, and masked-counts only; request bodies are never logged.

## 5. Known limitations (please read)

> Numbering follows [PRD §9](../docs/需求文档.md#9-已知限制与风险实测发现如实记录); not re-numbered here.

- **Transport coverage.** Clients using WebSocket or other non-HTTP channels cannot be intercepted in v0.1. Before integrating, confirm your client uses HTTP/SSE (e.g. Codex CLI with `wire_api = "responses"` and WebSocket disabled).
- **Recognition coverage.** Regex rules cannot catch every name, alias, or abbreviation. For high-sensitivity scenarios, add custom word lists (v0.2) or use a local/controlled environment.
- **Masking ≠ anonymization.** Placeholders prevent plaintext leakage, but context ("defendant, male, 30, Shenzhen") can still re-identify individuals.
- **Restore boundary.** Restore is exact-match only; placeholders rewritten by the model cannot be restored.

## 6. Threat model

| Direction | Covered? | Notes |
|---|---|---|
| Agent / user mistake leaks privacy outbound | ✅ mitigated | masked before leaving the machine |
| Third-party SDK attaches extra data to requests | ✅ mitigated | only whitelisted header fields are forwarded; bodies are masked |
| **Malicious web page in a browser sandbox (DNS rebinding / cross-site request)** | ✅ mitigated (v0.1 impl. req.) | gateway validates the `Host` header (loopback only), console rejects cross-origin `Origin`, write endpoints get a local token — prevents a rebinding page from reading restored plaintext via same-origin (FR-8) |
| Malicious code inside the gateway itself | ⚠️ residual | mitigations: code audit, loopback-only binding, least privilege, version pinning |
| Compromised local machine (malware) | ❌ not defended | user-space tools cannot defend against full local compromise |

## 7. Reporting vulnerabilities

We take security seriously. To report a vulnerability:

- **Do not** open a public issue for security problems.
- Email the maintainers directly (see the [README](../README.md) for contact), or use the repository's **private vulnerability reporting** if enabled.
- Include: affected version, steps to reproduce, expected vs. actual behavior, and a suggested fix if you have one.
- We aim to acknowledge within 48 hours and will coordinate a fix and disclosure timeline with you.

## 8. Uninstall

```bash
./install.sh --uninstall
rm -rf ~/.llm-sanitizer
```

Also revert your agent's `base_url` to the original provider (e.g. restore `~/.codex/config.toml`).
