"""config_manager 单元测试:检测 / 备份 / 接入 / 还原(FR-12)。

用临时 HOME 模拟 ~/.codex/config.toml,不触碰真实环境。
"""

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

    def test_apply_unsupported_agent(self):
        with self.assertRaises(ValueError):
            cm.apply("openclaw")


if __name__ == "__main__":
    unittest.main()
