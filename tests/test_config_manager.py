"""config_manager 单元测试:检测 / 备份 / 接入 / 还原(FR-12)。

用临时 HOME 模拟 ~/.codex/config.toml,不触碰真实环境。
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_sanitizer import config_manager as cm


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="llmsan-cm-")
        self._old_home = os.environ.get("HOME")
        self._old_profile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home  # Windows 的 Path.home() 优先读它
        os.environ["LLM_SANITIZER_HOME"] = str(Path(self.home) / ".llm-sanitizer")
        self.codex = Path(self.home) / ".codex" / "config.toml"
        self.codex.parent.mkdir(parents=True)
        self.orig = '[model]\nname = "gpt-4o"\n'
        self.codex.write_text(self.orig, encoding="utf-8")

    def tearDown(self):
        for k, v in (("HOME", self._old_home), ("USERPROFILE", self._old_profile)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_detect(self):
        agents = {a["id"]: a for a in cm.detect_agents()}
        self.assertTrue(agents["codex"]["detected"])
        self.assertFalse(agents["codex"]["applied"])
        self.assertTrue(agents["codex"]["auto"])
        self.assertTrue(agents["openclaw"]["auto"] is False)

    def test_apply_creates_backup_and_writes(self):
        r = cm.apply("codex")
        self.assertTrue(r["applied"])
        self.assertFalse(r["already"])
        self.assertTrue(Path(r["backup"]).exists(), "备份文件应存在")
        text = self.codex.read_text(encoding="utf-8")
        self.assertIn('[model_providers.llm-sanitizer]', text)
        self.assertIn('base_url = "http://127.0.0.1:8790/v1"', text)
        self.assertIn('model_provider = "llm-sanitizer"', text)
        self.assertIn(self.orig, text, "原配置内容必须保留")
        # 备份权限 600(Windows 由 LOCALAPPDATA ACL 承担)
        if sys.platform != "win32":
            self.assertEqual(os.stat(r["backup"]).st_mode & 0o777, 0o600)

    def test_apply_idempotent(self):
        cm.apply("codex")
        r2 = cm.apply("codex")
        self.assertTrue(r2["already"])
        self.assertEqual(r2["backup"], "", "已接入时不应再产生备份")
        self.assertEqual(len(cm.list_backups("codex")), 1, "只应备份一次")

    def test_detect_applied_after_apply(self):
        cm.apply("codex")
        agents = {a["id"]: a for a in cm.detect_agents()}
        self.assertTrue(agents["codex"]["applied"])

    def test_restore(self):
        cm.apply("codex")
        r = cm.restore("codex")
        self.assertTrue(r["restored"])
        self.assertEqual(self.codex.read_text(encoding="utf-8"), self.orig, "还原后应与原文一致")
        self.assertEqual(cm.list_backups("codex"), [], "还原后应移除本次备份")

    def test_restore_without_backup_raises(self):
        with self.assertRaises(FileNotFoundError):
            cm.restore("codex")

    def test_apply_missing_config_raises(self):
        self.codex.unlink()
        with self.assertRaises(FileNotFoundError):
            cm.apply("codex")

    def test_apply_toml_root_key(self):
        """P1 回归:model_provider 必须是根级键,不能落在 provider 表内(tomllib 断言)。"""
        cm.apply("codex")
        try:
            import tomllib
        except ImportError:  # Python 3.9/3.10
            self.skipTest("tomllib requires Python 3.11+")
        with open(self.codex, "rb") as f:
            data = tomllib.load(f)
        # 根级选择键生效(Codex 官方文档:根键必须在 table 之前)
        self.assertEqual(data.get("model_provider"), "llm-sanitizer")
        # 表内不得包含该键(旧 bug 特征:根键落入 [model_providers.llm-sanitizer])
        provider = data.get("model_providers", {}).get("llm-sanitizer", {})
        self.assertNotIn("model_provider", provider)
        self.assertEqual(provider.get("base_url"), "http://127.0.0.1:8790/v1")

    def _assert_toml_root_key(self, expected="llm-sanitizer"):
        """tomllib 断言根级 model_provider 生效且表内无该键。"""
        try:
            import tomllib
        except ImportError:  # Python 3.9/3.10
            self.skipTest("tomllib requires Python 3.11+")
        with open(self.codex, "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data.get("model_provider"), expected)
        provider = data.get("model_providers", {}).get("llm-sanitizer", {})
        self.assertNotIn("model_provider", provider)

    def _write_legacy_bad_config(self):
        """模拟旧版 connect 写入的坏配置:表存在,但根键落在了表内。"""
        self.codex.write_text(
            '[model_providers.llm-sanitizer]\n'
            'name = "LLM Sanitizer"\n'
            'base_url = "http://127.0.0.1:8790/v1"\n'
            'env_key = "LLM_SANITIZER_KEY"\n'
            'wire_api = "responses"\n'
            '\n'
            'model_provider = "llm-sanitizer"\n',
            encoding="utf-8",
        )

    def test_detect_legacy_bad_config_not_applied(self):
        """旧坏配置(根键缺失)detect 必须报未接入,而不是误报已接入。"""
        self._write_legacy_bad_config()
        agents = {a["id"]: a for a in cm.detect_agents()}
        self.assertFalse(agents["codex"]["applied"])

    def test_apply_migrates_legacy_bad_config(self):
        """迁移自愈:旧坏配置重跑 connect 补根键,Codex 实际切换 provider。"""
        self._write_legacy_bad_config()
        r = cm.apply("codex")
        self.assertTrue(r["applied"])
        self.assertFalse(r["already"])
        self.assertTrue(Path(r["backup"]).exists(), "迁移必须先备份")
        self._assert_toml_root_key("llm-sanitizer")
        # 原坏配置内容(表)保留,仅补根键
        text = self.codex.read_text(encoding="utf-8")
        self.assertIn('[model_providers.llm-sanitizer]', text)
        self.assertIn('wire_api = "responses"', text)

    def test_apply_migrate_is_idempotent(self):
        """迁移后再 connect 幂等跳过,不再产生新备份。"""
        self._write_legacy_bad_config()
        cm.apply("codex")
        r2 = cm.apply("codex")
        self.assertTrue(r2["already"])
        self.assertEqual(len(cm.list_backups("codex")), 1)

    def test_apply_replaces_existing_root_provider(self):
        """根级已有其他 provider(如 openai):接入时替换为 llm-sanitizer。"""
        orig = 'model = "gpt-5"\nmodel_provider = "openai"\n\n[mcp_servers.local]\ncommand = "npx"\n'
        self.codex.write_text(orig, encoding="utf-8")
        r = cm.apply("codex")
        self.assertTrue(r["applied"])
        self.assertFalse(r["already"])
        self._assert_toml_root_key("llm-sanitizer")
        text = self.codex.read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5"', text, "其他根键必须保留")
        self.assertIn("[mcp_servers.local]", text, "已有 table 必须保留")
        self.assertNotIn('model_provider = "openai"', text)

    def test_apply_ignores_commented_root_key(self):
        """头部注释里的 model_provider 不算已配置,必须真正插入根键。"""
        orig = '# model_provider = "openai"\nmodel = "gpt-5"\n'
        self.codex.write_text(orig, encoding="utf-8")
        cm.apply("codex")
        self._assert_toml_root_key("llm-sanitizer")

    def test_apply_unsupported_agent(self):
        with self.assertRaises(ValueError):
            cm.apply("openclaw")

    # ---- v0.6:Agent 扫描扩展 + Claude Code 自动接入 + 动态端口 ----

    def test_detect_scans_all_common_agents(self):
        """detect_agents 覆盖常见 AI 工具(配置或 CLI 任一命中即 detected)。"""
        agents = {a["id"]: a for a in cm.detect_agents()}
        for pid in ("codex", "claude", "gemini", "workbuddy", "openclaw", "opencode"):
            self.assertIn(pid, agents, f"缺少检测项 {pid}")
        self.assertTrue(agents["claude"]["auto"], "Claude Code 应支持一键接入")
        self.assertFalse(agents["gemini"]["auto"])

    def test_claude_detected_via_config(self):
        p = Path(self.home) / ".claude" / "settings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"model": "opus"}', encoding="utf-8")
        agents = {a["id"]: a for a in cm.detect_agents()}
        self.assertTrue(agents["claude"]["detected"])
        self.assertFalse(agents["claude"]["applied"])

    def test_apply_claude_writes_env_and_restores(self):
        p = Path(self.home) / ".claude" / "settings.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"model": "opus", "permissions": {"allow": ["Bash"]}}', encoding="utf-8")
        r = cm.apply("claude")
        self.assertTrue(r["applied"])
        self.assertFalse(r["already"])
        obj = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(obj["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8790/v1")
        self.assertIn("permissions", obj, "原字段必须保留")
        # 检测到已接入
        agents = {a["id"]: a for a in cm.detect_agents()}
        self.assertTrue(agents["claude"]["applied"])
        # 幂等
        r2 = cm.apply("claude")
        self.assertTrue(r2["already"])
        # 还原
        cm.restore("claude")
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"model": "opus", "permissions": {"allow": ["Bash"]}})

    def test_apply_claude_missing_config_raises(self):
        with self.assertRaises(FileNotFoundError):
            cm.apply("claude")

    def test_codex_uses_persisted_port(self):
        """v0.6:接入写入的 base_url 用持久化端口,而非写死 8790。"""
        os.environ["LLM_SANITIZER_PORT"] = "8792"
        try:
            cm.apply("codex")
        finally:
            os.environ.pop("LLM_SANITIZER_PORT", None)
        text = self.codex.read_text(encoding="utf-8")
        self.assertIn('base_url = "http://127.0.0.1:8792/v1"', text)


if __name__ == "__main__":
    unittest.main()
