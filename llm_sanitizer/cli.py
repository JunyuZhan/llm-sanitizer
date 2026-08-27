"""命令行入口:start / status / mask / restore / install / uninstall / upgrade。"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from llm_sanitizer import config, dashboard, gateway  # noqa: E402
    from llm_sanitizer.masker import mask_text, restore_text  # noqa: E402
else:
    from . import config, dashboard, gateway  # noqa: E402
    from .masker import mask_text, restore_text  # noqa: E402

from llm_sanitizer import __version__  # noqa: E402


def _version_tuple(v: str) -> tuple:
    """'1.2.3' → (1,2,3);非数字段忽略。"""
    return tuple(int(x) for x in re.split(r"[.-]", v) if x.isdigit())[:3] or (0,)


def check_update(current: str = __version__):
    """查询 PyPI 最新版本。失败静默返回 (current, False)。返回 (latest, has_new)。"""
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/llm-sanitizer-gateway/json",
            headers={"User-Agent": f"llm-sanitizer/{current}"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.load(r)
        latest = data["info"]["version"]
        return latest, _version_tuple(latest) > _version_tuple(current)
    except Exception:
        return current, False


def _print_update_hint():
    latest, has_new = check_update()
    if has_new:
        print(f"[llm-sanitizer] 发现新版本 {latest}(当前 {__version__}):")
        print("  pip install --upgrade llm-sanitizer-gateway   # 升级")
        print("  升级后重启自启: ./install.sh --uninstall && ./install.sh")


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
    if os.environ.get("LLM_SANITIZER_CHECK_UPDATE", "1") != "0":
        # 后台检查更新;隐私敏感可 LLM_SANITIZER_CHECK_UPDATE=0 关闭
        threading.Thread(target=_print_update_hint, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n[llm-sanitizer] 退出")
        gs.shutdown()
        ds.shutdown()


def cmd_status(args):
    from llm_sanitizer.events import read_stats_file, tail_events  # D1 修复:包内绝对导入

    gw = _check_port(config.gateway_port())
    db = _check_port(config.dashboard_port())
    stats = read_stats_file(config.events_path())
    total = int(stats.get("total_masked", 0))
    reqs_total = int(stats.get("total_requests", 0))
    if not total:  # 兼容旧数据(无 stats.json)
        events = tail_events(str(config.events_path()), limit=10000)
        total = len([e for e in events if e.get("kind") == "mask"])
        reqs_total = len([e for e in events if e.get("kind") == "request"])
    print(f"网关端口 {config.gateway_port()}: {'运行中' if gw else '未运行'}")
    print(f"看板端口 {config.dashboard_port()}: {'运行中' if db else '未运行'}")
    print(f"上游: {config.upstream()}")
    print(f"数据目录: {config.data_dir()}")
    print(f"累计脱敏: {total} 项，请求: {reqs_total} 次")


def ocr_supports(path: str) -> bool:
    """图片扩展名(png/jpg/…):走 OCR 脱敏分支。"""
    from llm_sanitizer import ocr

    return ocr.supports(path)


def cmd_mask(args):
    from llm_sanitizer.formats import mask_file, supports
    from llm_sanitizer.masker import Masker, load_wordlist_file

    src = Path(args.file)
    if args.wordlist:
        masker = Masker(wordlist=load_wordlist_file(args.wordlist))
    else:
        masker = None
    dest = Path(args.output) if args.output else src.with_name("masked_" + src.name)
    if supports(args.file):
        # docx/xlsx/pdf:保留格式脱敏(辅助链路:先脱敏文件再交 Agent)
        m = Masker() if masker is None else masker
        changed = mask_file(str(src), str(dest), m)
        if args.map:
            m.save(args.map)  # 原子写 + chmod 600(D7 修复)
        print(f"[ok] 已写入 {dest}(保留格式,改动 {changed} 个流/条目)")
    elif ocr_supports(args.file):
        # 图片(png/jpg/…):OCR 脱敏(可选依赖 [ocr])
        from llm_sanitizer import ocr

        if not ocr.engine_available():
            print("[llm-sanitizer] 图片 OCR 脱敏是可选功能,当前未安装依赖:")
            print(ocr.install_hint())
            return 1
        m = Masker() if masker is None else masker
        try:
            res = ocr.mask_image(
                str(src), str(dest) if args.output else None, m,
                redact=bool(getattr(args, "redact", False)),
                lang=getattr(args, "ocr_lang", None),
            )
        except ocr.OcrError as e:
            print(f"[llm-sanitizer] OCR 失败: {e}")
            return 1
        if args.map:
            m.save(args.map)  # 原子写 + chmod 600(D7 修复)
        mode = "打码图" if res["mode"] == "redact" else "脱敏文本"
        print(f"[ok] 已写入 {res['dest']}(OCR {mode},改动 {res['changed']} 个文本块)")
        for cat, n in sorted(m.counters.items()):
            print(f"  {cat}: {n}")
        if res["mode"] == "redact":
            print("[llm-sanitizer] 提示:打码不可逆;文本报告模式(默认)可还原")
    else:
        text = src.read_text(encoding="utf-8")
        if masker is None:
            masked, m = mask_text(text)
        else:
            masked, m = mask_text(text, masker)
        dest.write_text(masked, encoding="utf-8")
        if args.map:
            m.save(args.map)  # 原子写 + chmod 600(D7 修复)
        print(f"[ok] 已写入 {dest}")
        for cat, n in sorted(m.counters.items()):
            print(f"  {cat}: {n}")


def cmd_restore(args):
    import json

    from llm_sanitizer.formats import restore_file, supports

    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
    src = Path(args.file)
    dest = Path(args.output) if args.output else src.with_name("restored_" + src.name)
    if supports(args.file):
        changed = restore_file(str(src), str(dest), mapping)
        print(f"[ok] 已写入 {dest}(还原 {changed} 个流/条目)")
    elif ocr_supports(args.file):
        # 图片:打码不可逆;文本报告(.txt)请用文本分支还原
        print("[llm-sanitizer] 图片打码(redact)不可逆还原;若你脱敏的是文本报告,")
        print("  请对生成的 .txt 执行:llm-sanitizer restore masked_xx.txt --map ...")
        return 1
    else:
        text = src.read_text(encoding="utf-8")
        out = restore_text(text, mapping)
        dest.write_text(out, encoding="utf-8")
        print(f"[ok] 已写入 {dest}")


def _windows_schtasks_args():
    """Windows 自启:schtasks 注册登录时运行(普通用户可建自己的任务,免管理员)。
    参数生成抽成纯函数,便于测试且无副作用。"""
    return [
        "schtasks", "/Create", "/F", "/TN", "llm-sanitizer",
        "/TR", f'"{sys.executable}" -m llm_sanitizer start',
        "/SC", "ONLOGON", "/RL", "LIMITED",
    ]


def _windows_schtasks_delete_args():
    return ["schtasks", "/Delete", "/F", "/TN", "llm-sanitizer"]


def cmd_install(args):
    if os.name == "nt":
        # Windows:计划任务自启(免管理员);数据目录 %LOCALAPPDATA%\llm-sanitizer
        if args.uninstall:
            r = subprocess.run(_windows_schtasks_delete_args(), capture_output=True, text=True)
            if r.returncode == 0:
                print("[llm-sanitizer] 已移除计划任务 llm-sanitizer")
            else:
                print("[llm-sanitizer] 计划任务移除失败(可能未安装):")
                print("  " + " ".join(_windows_schtasks_delete_args()))
            print(f"[llm-sanitizer] 数据目录保留:{config.data_dir()}——如需彻底清理请手动删除")
        else:
            r = subprocess.run(_windows_schtasks_args(), capture_output=True, text=True)
            if r.returncode == 0:
                print("[llm-sanitizer] 已注册计划任务:登录自启(无需管理员权限)")
            else:
                print("[llm-sanitizer] 计划任务注册失败,请以管理员身份运行,或手动创建:")
                print("  " + " ".join(_windows_schtasks_args()))
        return
    script = Path(__file__).resolve().parent.parent / "install.sh"
    if not script.exists():
        print("[llm-sanitizer] install.sh 不随 pip 包分发;请从源码仓库获取:")
        print("  https://github.com/JunyuZhan/llm-sanitizer")
        return
    subprocess.run(["bash", str(script)] + (["--uninstall"] if args.uninstall else []))


def cmd_connect(args):
    """一键接入 Agent(FR-12):备份 → 写入网关 base_url。"""
    from llm_sanitizer import config_manager

    try:
        out = config_manager.apply(args.agent)
    except Exception as e:
        print(f"[llm-sanitizer] 接入失败:{e}")
        return 1
    if out.get("already"):
        print(f"[llm-sanitizer] {args.agent} 已接入,无需重复修改")
    else:
        print(f"[llm-sanitizer] {args.agent} 已接入(备份:{out.get('backup')})")
        print(f"[llm-sanitizer] 重启 {args.agent} 后生效;随时可用 `llm-sanitizer disconnect {args.agent}` 还原")
    return 0


def cmd_disconnect(args):
    """一键还原 Agent 配置。"""
    from llm_sanitizer import config_manager

    try:
        out = config_manager.restore(args.agent)
    except Exception as e:
        print(f"[llm-sanitizer] 还原失败:{e}")
        return 1
    print(f"[llm-sanitizer] 已还原配置:{out.get('path')}")
    return 0


def cmd_upgrade(args):
    latest, has_new = check_update()
    if has_new:
        print(f"[llm-sanitizer] 发现新版本 {latest}(当前 {__version__})")
    elif re.search(r"(dev|rc|\.a\d|\.b\d)", __version__):
        # 预发布版本比线上稳定版"新",但用户实际装的是未发布版——如实提示
        print(f"[llm-sanitizer] 当前 {__version__} 为预发布版本(线上稳定版 {latest})")
        print("[llm-sanitizer] 如无特殊需求,建议升级到正式版:")
    else:
        print(f"[llm-sanitizer] 当前已是最新版本({__version__})")
    print("[llm-sanitizer] 升级:")
    print("  pip install --upgrade llm-sanitizer-gateway")
    if os.name == "nt":
        print("[llm-sanitizer] 升级后重启开机自启服务:")
        print("  llm-sanitizer install --uninstall && llm-sanitizer install")
    else:
        print("[llm-sanitizer] 升级后重启开机自启服务:")
        print("  ./install.sh --uninstall && ./install.sh")
    print("[llm-sanitizer] 说明:升级不丢失映射/统计(map.json 格式稳定,ADR-2)")


def main():
    if os.name == "nt":
        # Windows 默认 stdout 编码 GBK,中文输出会 UnicodeEncodeError——强制 UTF-8
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    ap = argparse.ArgumentParser(description="LLM Sanitizer - 本地 AI 流量隐私网关")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("start", help="前台启动网关与看板")
    sub.add_parser("status", help="查看状态与统计")
    p_mask = sub.add_parser("mask", help="单文件脱敏")
    p_mask.add_argument("file")
    p_mask.add_argument("-o", "--output")
    p_mask.add_argument("--map")
    p_mask.add_argument("--wordlist", help="自定义敏感词表(每行一词,可 `词|类别`);默认读数据目录 wordlist.txt")
    p_mask.add_argument("--redact", action="store_true",
                        help="图片模式:敏感区域在原图上涂黑生成打码图(不可逆);默认输出脱敏文本报告")
    p_mask.add_argument("--ocr-lang", default=None,
                        help="OCR 语言(默认 chi_sim+eng);如 --ocr-lang eng")
    p_restore = sub.add_parser("restore", help="单文件还原")
    p_restore.add_argument("file")
    p_restore.add_argument("--map", required=True)
    p_restore.add_argument("-o", "--output")
    p_inst = sub.add_parser("install", help="安装为开机自启")
    p_inst.add_argument("--uninstall", action="store_true")
    p_upg = sub.add_parser("upgrade", help="检查更新并查看升级方法")
    p_con = sub.add_parser("connect", help="一键接入 Agent(当前支持 codex)")
    p_con.add_argument("agent")
    p_dis = sub.add_parser("disconnect", help="一键还原 Agent 配置")
    p_dis.add_argument("agent")
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
    elif args.cmd == "connect":
        return cmd_connect(args)
    elif args.cmd == "disconnect":
        return cmd_disconnect(args)
    elif args.cmd == "upgrade":
        cmd_upgrade(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
