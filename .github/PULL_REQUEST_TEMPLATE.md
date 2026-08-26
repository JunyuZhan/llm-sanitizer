<!-- 感谢提交 PR!请填写以下内容。Thanks for your PR! -->

## What does this PR do / 本次改动
Briefly describe the change.

## Related issue / 关联 issue
Closes #<issue-number>

## Checklist
- [ ] Ran `python3 tests/test_e2e.py` (once tests land)
- [ ] Updated docs if behavior changed (bilingual docs updated in sync: EN + zh-CN)
- [ ] Added tests for new/changed masking rules (hit sample + false-positive sample)
- [ ] Updated CHANGELOG.md (`Unreleased` section)

## Data-flow impact (REQUIRED for privacy-related changes / 隐私改动必填)
**任何涉及脱敏、还原、日志、映射存储的改动,必须填写本段;否则 PR 不会合并。**
**Any change touching masking/restore/logging/mapping storage MUST fill this out; otherwise the PR will not be merged.**

- 读取了哪些数据,流向何处? / What data is read and where does it go?
- 是否新增落盘的明文(权限)? / Any new plaintext persisted on disk (permissions)?
- 网关是否新增外部调用? / Any new external calls made by the gateway?

<!--
若本次改动不涉及隐私处理,请写明:
If this change does NOT touch privacy handling, state that explicitly:
"This change does not touch privacy handling: it only affects <non-privacy area>."
-->
