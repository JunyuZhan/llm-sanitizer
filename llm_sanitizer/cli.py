"""命令行入口：start / status / mask / restore / install / uninstall。"""

import argparse
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from llm_sanitizer import config, dashboard, gateway  # noqa: E402
    from llm_sanitizer.masker import mask_text, restore_text  # noqa: E402
else:
    from . import config, dashboard, gateway  # noqa: E402
    from .masker import mask_text, restore_text  # noqa: E402


def _check_port(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=1)
        s.close()
        return True
    except Exception:
        return False


def cmd_start(args):
    config.ensure_dirs()
    gateway.init_state()
    gs = gateway.create_gateway_server()
    ds = dashboard.create_dashboard_server()
    threading.Thread(target=gs.serve_forever, daemon=True).start()
    threading.Thread(target=ds.serve_forever, daemon=True).start()
    print(f"[llm-sanitizer] 网关  http://127.0.0.1:{config.gateway_port()}/v1")
    print(f"[llm-sanitizer] 看板  http://127.0.0.1:{config.dashboard_port()}")
    print(f"[llm-sanitizer] 上游  {config.upstream()}")
    print("[llm-sanitizer] Ctrl+C 退出")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[llm-sanitizer] 退出")
        gs.shutdown()
        ds.shutdown()


def cmd_status(args):
    from llm_sanitizer.events import tail_events  # D1 修复:包内绝对导入

    gw = _check_port(config.gateway_port())
    db = _check_port(config.dashboard_port())
    events = tail_events(str(config.events_path()), limit=10000)
    masked = [e for e in events if e.get("kind") == "mask"]
    reqs = [e for e in events if e.get("kind") == "request"]
    print(f"网关端口 {config.gateway_port()}: {'运行中' if gw else '未运行'}")
    print(f"看板端口 {config.dashboard_port()}: {'运行中' if db else '未运行'}")
    print(f"上游: {config.upstream()}")
    print(f"数据目录: {config.data_dir()}")
    print(f"累计脱敏: {len(masked)} 项，请求: {len(reqs)} 次")


def cmd_mask(args):
    src = Path(args.file)
    text = src.read_text(encoding="utf-8")
    masked, m = mask_text(text)
    dest = Path(args.output) if args.output else src.with_name("masked_" + src.name)
    dest.write_text(masked, encoding="utf-8")
    if args.map:
        m.save(args.map)  # 原子写 + chmod 600(D7 修复)
    print(f"[ok] 已写入 {dest}")
    for cat, n in sorted(m.counters.items()):
        print(f"  {cat}: {n}")


def cmd_restore(args):
    import json

    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
    src = Path(args.file)
    text = src.read_text(encoding="utf-8")
    out = restore_text(text, mapping)
    dest = Path(args.output) if args.output else src.with_name("restored_" + src.name)
    dest.write_text(out, encoding="utf-8")
    print(f"[ok] 已写入 {dest}")


def cmd_install(args):
    script = Path(__file__).resolve().parent.parent / "install.sh"
    if not script.exists():
        print("[llm-sanitizer] install.sh 不随 pip 包分发;请从源码仓库获取:")
        print("  https://github.com/JunyuZhan/llm-sanitizer")
        return
    subprocess.run(["bash", str(script)] + (["--uninstall"] if args.uninstall else []))


def main():
    ap = argparse.ArgumentParser(description="LLM Sanitizer - 本地 AI 流量隐私网关")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("start", help="前台启动网关与看板")
    sub.add_parser("status", help="查看状态与统计")
    p_mask = sub.add_parser("mask", help="单文件脱敏")
    p_mask.add_argument("file")
    p_mask.add_argument("-o", "--output")
    p_mask.add_argument("--map")
    p_restore = sub.add_parser("restore", help="单文件还原")
    p_restore.add_argument("file")
    p_restore.add_argument("--map", required=True)
    p_restore.add_argument("-o", "--output")
    p_inst = sub.add_parser("install", help="安装为开机自启")
    p_inst.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
    if args.cmd == "start":
        cmd_start(args)
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "mask":
        cmd_mask(args)
    elif args.cmd == "restore":
        cmd_restore(args)
    elif args.cmd == "install":
        cmd_install(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
