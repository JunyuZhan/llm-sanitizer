"""看板前端完整性测试(v0.6.1):PAGE 模板的 JS 不得出现语法级错误。

背景:v0.5 引入 `def loadSettings() {`(Python 关键字混入 JS),导致整个
<script> 块语法错误、一行不跑——统计永远 0、Agent 永远"检测中…",且
curl/API 测试全部正常,只有浏览器渲染才暴露。本测试做静态守卫:
- PAGE 内不允许行首 `def `(JS 没有 def 关键字)
- 关键函数必须存在且数量正确
- 可选:node --check 深度校验(CI 有 node;本地缺失时跳过)
"""

import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestDashboardTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from llm_sanitizer import dashboard

        cls.page = dashboard.PAGE
        m = re.search(r"<script>(.*?)</script>", cls.page, re.S)
        cls.js = m.group(1) if m else ""

    def test_no_python_def_in_js(self):
        """JS 块内不允许行首 `def `(Python 关键字;v0.5 笔误即此类)。"""
        for line in self.js.splitlines():
            stripped = line.lstrip()
            self.assertFalse(
                stripped.startswith("def "),
                f"JS 中出现 Python 关键字 def: {line!r}",
            )

    def test_key_functions_present(self):
        for fn in ("refresh", "loadAgents", "loadSettings", "agentAction", "renderCats"):
            self.assertIn(f"function {fn}(", self.js, f"缺少函数 {fn}")

    def test_agent_switch_ui_present(self):
        """v0.6:开关式 Agent 列表文案存在。"""
        self.assertIn("开启脱敏", self.page)
        self.assertIn("关闭脱敏", self.page)
        self.assertIn("本机 AI 工具", self.page)

    def test_advanced_settings_collapsed(self):
        """v0.6:上游地址等收进「高级设置」折叠,主界面不再暴露 URL 表单。"""
        self.assertIn("<details>", self.page)
        self.assertIn("高级设置", self.page)

    def test_node_syntax_check(self):
        """有 node 时深度校验 JS 语法(CI/本地有 node 则跑,缺失跳过)。"""
        node = shutil.which("node")
        if not node:
            self.skipTest("本机无 node,跳过深度语法校验")
        r = subprocess.run(
            [node, "--check", "-"],
            input=self.js.encode("utf-8"),
            capture_output=True,
        )
        self.assertEqual(
            r.returncode, 0,
            f"JS 语法错误:\n{r.stderr.decode('utf-8', 'replace')}",
        )


if __name__ == "__main__":
    unittest.main()
