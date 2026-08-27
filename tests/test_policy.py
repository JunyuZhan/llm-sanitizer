"""组织策略 + 审计导出测试(v0.5)。

- 策略合并:enforced(强制开)/ blocked(强制关)优先级高于用户设置
- 审计导出:CSV/JSON 只含占位符无明文、--since 过滤、600 权限
- 留存清理:超期事件文件删除、stats.json 不受影响
"""

import csv
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_sanitizer import config as cfg  # noqa: E402
from llm_sanitizer.events import EventStore, cleanup_old_events, read_all_events  # noqa: E402


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="llmsan-pol-")
        self._old_home = os.environ.get("LLM_SANITIZER_HOME")
        os.environ["LLM_SANITIZER_HOME"] = self.home

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("LLM_SANITIZER_HOME", None)
        else:
            os.environ["LLM_SANITIZER_HOME"] = self._old_home

    def _write_policy(self, data):
        p = cfg.policy_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")

    def test_no_policy_defaults_all_on(self):
        """无策略文件:全类别启用。"""
        self.assertEqual(cfg.disabled_categories(), set())

    def test_enforced_overrides_user_disabled(self):
        """用户关闭了手机号,但策略强制开启 → 手机号仍生效。"""
        self._write_policy({"enforced_categories": ["手机号"]})
        s = cfg.settings_path()
        s.parent.mkdir(parents=True, exist_ok=True)
        s.write_text(json.dumps({"categories": ["姓名", "邮箱"]}), encoding="utf-8")
        disabled = cfg.disabled_categories()
        self.assertNotIn("手机号", disabled, "策略强制开启的类别不能被用户关闭")
        self.assertNotIn("姓名", disabled, "用户设置中的类别保持启用")
        self.assertIn("地址", disabled, "未在用户设置中的类别仍关闭")

    def test_blocked_forces_off(self):
        """策略强制关闭:即使全开也生效。"""
        self._write_policy({"blocked_categories": ["案号"]})
        s = cfg.settings_path()
        s.parent.mkdir(parents=True, exist_ok=True)
        from llm_sanitizer.masker import ALL_CATEGORIES

        s.write_text(json.dumps({"categories": list(ALL_CATEGORIES)}), encoding="utf-8")
        self.assertIn("案号", cfg.disabled_categories())

    def test_enabled_categories_snapshot(self):
        """enabled_categories 与 disabled 互补(全集 − 禁用 = 启用)。"""
        from llm_sanitizer.masker import ALL_CATEGORIES

        self._write_policy({"enforced_categories": ["手机号"]})
        enabled = cfg.enabled_categories()
        self.assertIn("手机号", enabled)
        self.assertEqual(enabled, set(ALL_CATEGORIES) - cfg.disabled_categories())

    def test_retention_days(self):
        self.assertEqual(cfg.retention_days(), 90)
        self._write_policy({"retention_days": 7})
        self.assertEqual(cfg.retention_days(), 7)
        self._write_policy({"retention_days": "bad"})
        self.assertEqual(cfg.retention_days(), 90)


class TestAuditExport(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="llmsan-aud-")
        self._old_home = os.environ.get("LLM_SANITIZER_HOME")
        os.environ["LLM_SANITIZER_HOME"] = self.home
        self.events_path = str(cfg.events_path())

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("LLM_SANITIZER_HOME", None)
        else:
            os.environ["LLM_SANITIZER_HOME"] = self._old_home

    def _seed(self, rotate=100000):
        """默认大轮转阈值避免测试数据被轮转丢弃(真实场景 5MB 阈值足够)。"""
        store = EventStore(self.events_path, rotate_bytes=rotate)
        for i in range(40):
            store.add("mask", category="姓名", token=f"[姓名_{i}]")
            if i % 10 == 0:
                store.add("request", method="POST", path="/v1/chat/completions", new_findings=1)
        return store

    def test_read_all_events_includes_rotated(self):
        """审计全量读取:主文件 + 三份轮转历史(.1/.2/.3)按旧→新合并。"""
        import json as _json

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            # 手动构造 3 份历史 + 主文件
            for n in (3, 2, 1):
                with open(path + f".{n}", "w", encoding="utf-8") as f:
                    for i in range(5):
                        f.write(_json.dumps({"ts": "2026-08-27 00:00:00", "kind": "mask",
                                             "category": "姓名", "token": f"[姓名_{n}_{i}]"}) + "\n")
            with open(path, "w", encoding="utf-8") as f:
                for i in range(5):
                    f.write(_json.dumps({"ts": "2026-08-27 00:00:00", "kind": "mask",
                                         "category": "姓名", "token": f"[姓名_0_{i}]"}) + "\n")
            all_ev = read_all_events(path)
            self.assertEqual(len(all_ev), 20, "主文件+3 份历史应全量合并")
            # 顺序:旧(.3)→ 新(主文件)
            self.assertEqual(all_ev[0]["token"], "[姓名_3_0]")
            self.assertEqual(all_ev[-1]["token"], "[姓名_0_4]")

    def test_rotation_keeps_incremental_history(self):
        """轮转保留 .1/.2/.3 递增历史(最旧丢弃),不再单份覆盖。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            store = EventStore(path, rotate_bytes=200)
            for i in range(30):
                store.add("mask", category="姓名", token=f"[姓名_{i}]")
            for n in (1, 2, 3):
                self.assertTrue(os.path.exists(path + f".{n}"), f"轮转历史 .{n} 应存在")
            # 主文件仍可继续追加
            store.add("mask", category="手机号", token="[手机号_1]")
            self.assertEqual(len(read_all_events(path)), len(read_all_events(path)))  # 不抛异常
            self.assertTrue(any(e["token"] == "[手机号_1]" for e in read_all_events(path)))

    def _run_cli(self, *args):
        import subprocess, sys as _s

        r = subprocess.run(
            [_s.executable, "-m", "llm_sanitizer", *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        return r

    def test_export_csv_no_plaintext(self):
        """CSV 导出:含轮转历史全量事件、只有占位符无明文、权限 600。"""
        self._seed()
        out = os.path.join(self.home, "audit.csv")
        r = self._run_cli("audit-export", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertGreaterEqual(len(rows), 44)  # 40 mask + 4 request,含轮转历史
        self.assertIn("[姓名_39]", {row["token"] for row in rows if row["kind"] == "mask"})
        self.assertNotIn("明文", "".join(row["category"] + row["token"] for row in rows))
        if sys.platform != "win32":
            self.assertEqual(os.stat(out).st_mode & 0o777, 0o600)

    def test_export_json_summary(self):
        """JSON 导出:含累计汇总(by_category 不倒退)。"""
        self._seed()
        out = os.path.join(self.home, "audit.json")
        r = self._run_cli("audit-export", "--json", "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(data["summary"]["total_masked"], 40)
        self.assertEqual(data["summary"]["by_category"]["姓名"], 40)
        self.assertEqual(data["summary"]["total_requests"], 4)

    def test_export_since_filter(self):
        """--since 过滤:今天之前的事件被排除(事件含日期)。"""
        self._seed()
        today = time.strftime("%Y-%m-%d")
        out = os.path.join(self.home, "audit_today.csv")
        r = self._run_cli("audit-export", "--since", today, "-o", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertGreaterEqual(len(rows), 44, "今天的事件应全部包含")
        bad = self._run_cli("audit-export", "--since", "1999-01-01", "-o", os.path.join(self.home, "a.csv"))
        self.assertEqual(bad.returncode, 0)

    def test_cleanup_old_events(self):
        """留存清理:超期事件文件删除,stats.json 不受影响。"""
        self._seed()
        sp = self.events_path + ".stats.json"
        self.assertTrue(os.path.exists(sp))
        # 把事件文件 mtime 改为 100 天前 → 应被清理
        old = time.time() - 100 * 86400
        for p in (self.events_path, self.events_path + ".1"):
            if os.path.exists(p):
                os.utime(p, (old, old))
        removed = cleanup_old_events(self.events_path, 90)
        self.assertGreaterEqual(len(removed), 1, "超期事件文件应被删除")
        self.assertTrue(os.path.exists(sp), "累计统计不受留存清理影响")
        # 新事件文件不受影响
        self._seed()
        removed2 = cleanup_old_events(self.events_path, 90)
        self.assertEqual(removed2, [], "新文件不应被清理")


if __name__ == "__main__":
    unittest.main()
