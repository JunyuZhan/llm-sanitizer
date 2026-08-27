"""EventStore 单元测试:追加写、轮转(P3 修复)、累计统计持久化(FR-5 修订)。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_sanitizer.events import EventStore, read_stats_file, tail_events


class TestEventStore(unittest.TestCase):
    def test_append_and_tail(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            store = EventStore(path)
            store.add("mask", category="姓名", token="[姓名_1]")
            store.add("request", method="POST", path="/v1/chat/completions", new_findings=1)
            events = tail_events(path, limit=10)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["kind"], "mask")
            self.assertNotIn("明文", str(events))  # 事件不含明文(本用例即无明文)

    def test_rotate_when_large(self):
        """P3:事件文件超阈值自动轮转(events.jsonl → events.jsonl.1),防无限增长。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            store = EventStore(path, rotate_bytes=200)
            for i in range(60):
                store.add("mask", category="姓名", token=f"[姓名_{i}]")
            self.assertTrue(os.path.exists(path), "新事件文件应存在")
            self.assertTrue(os.path.exists(path + ".1"), "历史文件应轮转为 .1")
            # 轮转后仍可继续追加并被尾部读取
            store.add("mask", category="手机号", token="[手机号_9]")
            tail = tail_events(path, limit=3)
            self.assertEqual(tail[-1]["token"], "[手机号_9]")

    def test_stats(self):
        with tempfile.TemporaryDirectory() as d:
            store = EventStore(os.path.join(d, "events.jsonl"))
            store.add("mask", category="姓名", token="[姓名_1]")
            store.add("mask", category="姓名", token="[姓名_2]")
            store.add("request", method="POST", path="/v1/chat/completions", new_findings=2)
            s = store.stats()
            self.assertEqual(s["total_masked"], 2)
            self.assertEqual(s["by_category"].get("姓名"), 2)
            self.assertEqual(s["total_requests"], 1)

    def test_stats_persist_across_restart(self):
        """FR-5 修订:累计计数持久化到 stats.json——新实例(模拟重启)不归零。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            store = EventStore(path)
            store.add("mask", category="姓名", token="[姓名_1]")
            store.add("mask", category="手机号", token="[手机号_1]")
            store.add("request", method="POST", path="/v1/chat/completions", new_findings=2)
            # 重启:新实例从 stats.json 恢复
            store2 = EventStore(path)
            s = store2.stats()
            self.assertEqual(s["total_masked"], 2)
            self.assertEqual(s["by_category"].get("姓名"), 1)
            self.assertEqual(s["by_category"].get("手机号"), 1)
            self.assertEqual(s["total_requests"], 1)
            # dashboard 独立读取同源
            self.assertEqual(read_stats_file(path)["total_masked"], 2)

    def test_stats_survive_rotation(self):
        """FR-5 修订:事件文件轮转后累计计数不倒退(看板读 stats 而非事件尾部)。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            store = EventStore(path, rotate_bytes=200)
            for i in range(60):
                store.add("mask", category="姓名", token=f"[姓名_{i}]")
            # 轮转触发后:事件文件只剩少量,但累计计数保持 60
            self.assertTrue(os.path.exists(path + ".1"))
            store.add("mask", category="手机号", token="[手机号_1]")
            s = store.stats()
            self.assertEqual(s["total_masked"], 61, "轮转后累计计数不得倒退")
            self.assertEqual(s["by_category"].get("姓名"), 60)
            self.assertEqual(s["by_category"].get("手机号"), 1)
            # 事件尾部(展示用)远小于累计
            self.assertLess(len(tail_events(path, limit=100)), 61)

    def test_stats_perm_600(self):
        """累计统计文件与 map.json 同级:权限 600。"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            store = EventStore(path)
            store.add("mask", category="姓名", token="[姓名_1]")
            if sys.platform != "win32":  # Windows 由 LOCALAPPDATA ACL 承担
                mode = os.stat(path + ".stats.json").st_mode & 0o777
                self.assertEqual(mode, 0o600, f"stats.json 权限应为 600,实际 {oct(mode)}")


if __name__ == "__main__":
    unittest.main()
