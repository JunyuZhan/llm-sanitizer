"""CLI 冒烟测试:python3 -m llm_sanitizer mask/restore 端到端可用(__main__ 入口)。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


class TestCLI(unittest.TestCase):
    def _run(self, *args, env=None):
        return subprocess.run(
            [PY, "-m", "llm_sanitizer", *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env={**os.environ, **(env or {})},
        )

    def test_mask_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.txt")
            masked_path = os.path.join(d, "masked.txt")
            restored_path = os.path.join(d, "restored.txt")
            map_path = os.path.join(d, "map.json")
            with open(src, "w", encoding="utf-8") as f:
                f.write("原告张三,电话13912345678\n")

            r = self._run("mask", src, "-o", masked_path, "--map", map_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(masked_path, encoding="utf-8") as f:
                masked = f.read()
            self.assertIn("[姓名_1]", masked)
            self.assertNotIn("张三", masked)
            # 映射文件权限 600(D7)
            self.assertEqual(os.stat(map_path).st_mode & 0o777, 0o600)

            r = self._run("restore", masked_path, "--map", map_path, "-o", restored_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(restored_path, encoding="utf-8") as f:
                restored = f.read()
            self.assertEqual(restored, "原告张三,电话13912345678\n")

    def test_mask_with_wordlist(self):
        """v0.2:CLI mask --wordlist 生效(词表命中 + 还原)。"""
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.txt")
            masked_path = os.path.join(d, "masked.txt")
            map_path = os.path.join(d, "map.json")
            wl = os.path.join(d, "wl.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write("张三丰 电话13912345678\n")
            with open(wl, "w", encoding="utf-8") as f:
                f.write("张三丰|姓名\n")

            r = self._run("mask", src, "-o", masked_path, "--map", map_path, "--wordlist", wl)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(masked_path, encoding="utf-8") as f:
                masked = f.read()
            self.assertIn("[姓名_1]", masked)
            self.assertNotIn("张三丰", masked)
            self.assertIn("[手机号_1]", masked)

    def test_status_runs(self):
        r = self._run("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("上游", r.stdout)

    def test_version_compare(self):
        from llm_sanitizer.cli import _version_tuple

        self.assertGreater(_version_tuple("1.2.3"), _version_tuple("1.2.2"))
        self.assertGreater(_version_tuple("1.10.0"), _version_tuple("1.9.9"))
        self.assertEqual(_version_tuple("1.2.3"), _version_tuple("1.2.3"))
        self.assertLess(_version_tuple("0.1.0"), _version_tuple("0.1.1"))

    def test_upgrade_cmd(self):
        r = self._run("upgrade")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pip install --upgrade", r.stdout)


if __name__ == "__main__":
    unittest.main()
