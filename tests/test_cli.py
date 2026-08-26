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

    def test_status_runs(self):
        r = self._run("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("上游", r.stdout)


if __name__ == "__main__":
    unittest.main()
