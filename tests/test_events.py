"""EventStore 单元测试:追加写、轮转(P3 修复)。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_sanitizer.events import EventStore, tail_events


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
            self.assertEqual(s["requests"], 1)


if __name__ == "__main__":
    unittest.main()
