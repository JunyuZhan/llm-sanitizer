"""事件存储：JSONL 追加写，线程安全。

设计约束：事件只记录占位符/类别/时间/请求路径，**绝不记录明文**。
明文只在 map.json 中，供还原使用。
"""

import json
import os
import threading
import time
from collections import deque


class EventStore:
    def __init__(self, path, max_memory=500):
        self.path = path
        self.max_memory = max_memory
        self._events = deque(maxlen=max_memory)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            if self.path and os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self._events.append(json.loads(line))
        except Exception:
            pass

    def add(self, kind, **fields):
        ev = {"ts": time.strftime("%H:%M:%S"), "kind": kind}
        ev.update(fields)
        with self._lock:
            self._events.append(ev)
            try:
                if self.path:
                    os.makedirs(os.path.dirname(self.path), exist_ok=True)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    os.chmod(self.path, 0o600)  # 敏感文件统一 600(FR-8/D7)
            except Exception:
                pass
        return ev

    def snapshot(self, limit=None):
        with self._lock:
            events = list(self._events)
        return events[-limit:] if limit else events

    def stats(self):
        events = self.snapshot()
        masked = [e for e in events if e.get("kind") == "mask"]
        by_cat = {}
        for e in masked:
            c = e.get("category", "?")
            by_cat[c] = by_cat.get(c, 0) + 1
        requests = [e for e in events if e.get("kind") == "request"]
        return {
            "total_masked": len(masked),
            "by_category": by_cat,
            "requests": len(requests),
        }


def tail_events(path, limit=300):
    """从事件文件尾部倒读最近 N 条(不读全文件,文件增长不影响性能)。
    供看板进程独立读取,不依赖网关内存。"""
    out = []
    if not path or not os.path.exists(path):
        return out
    try:
        size = os.path.getsize(path)
        if size == 0:
            return out
        block = 8192
        read_from = max(0, size - block)
        data = b""
        with open(path, "rb") as f:
            while True:
                f.seek(read_from)
                data = f.read()
                if read_from == 0 or data.count(b"\n") >= limit + 2:
                    break
                read_from = max(0, read_from - block)
        text = data.decode("utf-8", "replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out
    except Exception:
        return out
