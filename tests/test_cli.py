"""CLI 冒烟测试:python3 -m llm_sanitizer mask/restore 端到端可用(__main__ 入口)。"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


class TestUpgradeHints(unittest.TestCase):
    def test_upgrade_prerelease_hint(self):
        """v0.4.1:预发布版本且线上无更新时,如实提示'预发布'而非误导'已是最新'。"""
        from llm_sanitizer import cli

        buf = io.StringIO()
        with mock.patch.object(cli, "check_update", return_value=("0.4.0", False)), \
             mock.patch.object(cli, "__version__", "0.4.1.dev1"), \
             contextlib.redirect_stdout(buf):
            cli.cmd_upgrade(None)
        out = buf.getvalue()
        self.assertIn("预发布版本", out)
        self.assertIn("0.4.1.dev1", out)
        self.assertNotIn("当前已是最新版本", out)

    def test_upgrade_stable_latest(self):
        """稳定版且线上无更新时,保持原提示。"""
        from llm_sanitizer import cli

        buf = io.StringIO()
        with mock.patch.object(cli, "check_update", return_value=("0.4.1", False)), \
             mock.patch.object(cli, "__version__", "0.4.1"), \
             contextlib.redirect_stdout(buf):
            cli.cmd_upgrade(None)
        self.assertIn("当前已是最新版本", buf.getvalue())


class TestCLI(unittest.TestCase):
    def _run(self, *args, env=None):
        return subprocess.run(
            [PY, "-m", "llm_sanitizer", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",   # child 已强制 UTF-8 输出(Windows 修复)
            errors="replace",
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
            if sys.platform != "win32":  # Windows 由 LOCALAPPDATA ACL 承担
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

    @unittest.skipIf(sys.platform == "win32",
                     "Windows 自启由 CLI 的 schtasks 实现,不经过 bash install.sh")
    def test_installer_dry_run(self):
        """install.sh dry-run:macOS 生成的 plist 必须是合法 XML(非法会被 launchd 拒收)。"""
        with tempfile.TemporaryDirectory() as d:
            env = {
                **os.environ,
                "HOME": d,
                "LLM_SANITIZER_HOME": os.path.join(d, ".llm-sanitizer"),
                "LLM_SANITIZER_DRY_RUN": "1",
            }
            r = subprocess.run(["bash", "install.sh"], capture_output=True, text=True,
                               cwd=ROOT, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            if sys.platform == "darwin":
                plist = os.path.join(d, "Library", "LaunchAgents", "com.llmsanitizer.gateway.plist")
                self.assertTrue(os.path.exists(plist), "plist 未生成")
                import xml.etree.ElementTree as ET

                tree = ET.parse(plist)  # 非法 XML 在此抛 ParseError
                strings = [s.text for s in tree.iter("string")]
                self.assertIn("start", strings, f"ProgramArguments 缺 start: {strings}")
                self.assertIn("llm_sanitizer", strings)
                # 不允许残留字面量 \\n(旧 bug 特征)
                raw = open(plist, encoding="utf-8").read()
                self.assertNotIn("\\n", raw)
            else:
                unit = os.path.join(d, ".config", "systemd", "user", "llm-sanitizer.service")
                self.assertTrue(os.path.exists(unit), "systemd unit 未生成")
                text = open(unit, encoding="utf-8").read()
                self.assertIn("ExecStart=", text)

    def test_windows_schtasks_args(self):
        """v0.3:Windows 自启 schtasks 参数构造(纯函数,无副作用)。"""
        from llm_sanitizer.cli import _windows_schtasks_args, _windows_schtasks_delete_args

        args = _windows_schtasks_args()
        self.assertEqual(args[0], "schtasks")
        self.assertIn("/Create", args)
        self.assertIn("/TN", args)
        self.assertIn("llm-sanitizer", args)
        self.assertIn("/SC", args)
        self.assertIn("ONLOGON", args)
        self.assertIn("start", args[args.index("/TR") + 1])
        d = _windows_schtasks_delete_args()
        self.assertIn("/Delete", d)
        self.assertIn("/F", d)

    def test_windows_data_dir(self):
        """v0.3:Windows 数据目录走 %LOCALAPPDATA%\\llm-sanitizer(ACL 隔离替代 600 语义)。
        断言平台无关(macOS 上 os.path 按 posix 拼接,分隔符归一化后比较)。"""
        from llm_sanitizer import config as cfg

        p = cfg._windows_data_dir(r"C:\Users\test\AppData\Local")
        norm = p.replace("\\", "/")
        self.assertTrue(norm.endswith("llm-sanitizer"), p)
        self.assertTrue(norm.startswith("C:/Users/test/AppData/Local"), p)
        # 环境变量(LLM_SANITIZER_HOME)仍最高优先级(经 data_dir 主路径)
        with mock.patch.dict(os.environ, {"LLM_SANITIZER_HOME": r"D:\custom"}, clear=False):
            self.assertEqual(str(cfg.data_dir()), r"D:\custom")

    def test_status_runs(self):
        r = self._run("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("上游", r.stdout)

    def test_desktop_hint_without_extra(self):
        """v0.5:未装 [desktop] extra 时,desktop 命令给出友好安装提示。"""
        from llm_sanitizer import desktop

        if desktop.available():
            self.skipTest("本机已装 pywebview,跳过提示分支")
        r = self._run("desktop")
        self.assertEqual(r.returncode, 1)
        self.assertIn("[desktop]", r.stdout)

    def test_packaging_artifacts(self):
        """v0.5:独立包构建脚本存在(spec 含全部模块 hiddenimports)。"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = os.path.join(root, "packaging", "llm_sanitizer.spec")
        build = os.path.join(root, "packaging", "build.py")
        self.assertTrue(os.path.exists(spec), "spec 应存在")
        self.assertTrue(os.path.exists(build), "build.py 应存在")
        with open(spec, encoding="utf-8") as f:
            content = f.read()
        for mod in ("llm_sanitizer.masker", "llm_sanitizer.gateway", "llm_sanitizer.cli"):
            self.assertIn(mod, content, f"spec 应包含 {mod}")

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
