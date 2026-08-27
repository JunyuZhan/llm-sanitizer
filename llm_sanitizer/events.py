"""事件存储：JSONL 追加写，线程安全。

设计约束：事件只记录占位符/类别/时间/请求路径，**绝不记录明文**。
明文只在 map.json 中，供还原使用。

**累计统计(FR-5 修订)**：`stats.json`(同目录,权限 600)持久化 per-category
计数器——看板"累计脱敏数"不随事件文件轮转/超尾而倒退,也不随网关重启归零。
事件文件本身只做最近事件的展示与轮转。
"""

import json
import os
import tempfile
import threading
import time
from collections import deque


class EventStore:
    def __init__(self, path, max_memory=500, rotate_bytes=5 * 1024 * 1024):
        self.path = path
        self.max_memory = max_memory
        self.rotate_bytes = rotate_bytes  # 事件文件超过该字节数时轮转(P3:防无限增长)
        self._events = deque(maxlen=max_memory)
        self._lock = threading.Lock()
        self._stats = {"total_masked": 0, "total_requests": 0, "by_category": {}}
        self._stats_path = (str(path) + ".stats.json") if path else None
        self._load()
        self._load_stats()

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

    def _load_stats(self):
        """读取持久化累计计数(重启不归零、轮转不倒退)。"""
        try:
            if self._stats_path and os.path.exists(self._stats_path):
                with open(self._stats_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._stats.update(data)
                    if not isinstance(self._stats.get("by_category"), dict):
                        self._stats["by_category"] = {}
        except Exception:
            pass

    def _save_stats(self):
        """原子写 + chmod 600(与 map.json 同级敏感文件)。"""
        try:
            if not self._stats_path:
                return
            d = os.path.dirname(self._stats_path) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".stats-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._stats, f, ensure_ascii=False, indent=2)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self._stats_path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        except Exception:
            pass

    def _rotate(self):
        """把当前事件文件轮转为 events.jsonl.1(保留 1 份历史),再开新文件。"""
        try:
            if os.path.exists(self.path):
                os.replace(self.path, self.path + ".1")
            open(self.path, "a", encoding="utf-8").close()
        except Exception:
            pass

    def add(self, kind, **fields):
        ev = {"ts": time.strftime("%H:%M:%S"), "kind": kind}
        ev.update(fields)
        with self._lock:
            self._events.append(ev)
            # 累计统计持久化(FR-5 修订):看板读 stats,不随事件尾部/轮转倒退
            if kind == "mask":
                self._stats["total_masked"] += 1
                c = fields.get("category") or "?"
                bc = self._stats.setdefault("by_category", {})
                bc[c] = bc.get(c, 0) + 1
            elif kind == "request":
                self._stats["total_requests"] = self._stats.get("total_requests", 0) + 1
            if kind in ("mask", "request"):
                self._save_stats()
            try:
                if self.path:
                    os.makedirs(os.path.dirname(self.path), exist_ok=True)
                    if os.path.exists(self.path) and os.path.getsize(self.path) > self.rotate_bytes:
                        self._rotate()
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
        """持久化累计统计(重启/轮转不丢)。"""
        with self._lock:
            return {
                "total_masked": self._stats.get("total_masked", 0),
                "total_requests": self._stats.get("total_requests", 0),
                "by_category": dict(self._stats.get("by_category", {})),
            }


def read_stats_file(path):
    """dashboard 进程独立读取持久化累计统计(不依赖网关内存/事件尾部)。"""
    try:
        sp = str(path) + ".stats.json"
        if os.path.exists(sp):
            with open(sp, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


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
