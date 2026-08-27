"""命令行入口:start / status / mask / restore / install / uninstall / upgrade。"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
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


def _probe_port(port):
    """探测端口上运行的服务归属,见 gateway.probe_port。"""
    return gateway.probe_port(port)


def cmd_start(args):
    config.ensure_dirs()
    # 组织策略留存:启动时清理超过 retention_days 的事件文件(静默,不阻塞)
    try:
        from llm_sanitizer.events import cleanup_old_events

        cleanup_old_events(str(config.events_path()), config.retention_days())
    except Exception:
        pass
    gw_port = int(args.port) if getattr(args, "port", None) else config.gateway_port()
    db_port = int(args.dashboard_port) if getattr(args, "dashboard_port", None) else config.dashboard_port()
    # 端口预检:已被占用时给出可操作提示,而不是裸 traceback
    gw_state = _probe_port(gw_port)
    if gw_state == "self":
        print(f"[llm-sanitizer] 网关已在运行(端口 {gw_port}),无需重复启动。")
        print(f"[llm-sanitizer] 看板  http://127.0.0.1:{db_port}")
        print(f"[llm-sanitizer] 查看状态: llm-sanitizer status")
        return
    if gw_state == "other":
        print(f"[llm-sanitizer] 端口 {gw_port} 已被其他程序占用,网关无法启动。")
        print(f"[llm-sanitizer] 换端口启动: llm-sanitizer start --port 8792")
        print(f"[llm-sanitizer] 或先停掉占用 {gw_port} 端口的程序再重试。")
        return
    db_state = _probe_port(db_port)
    if db_state == "other":
        print(f"[llm-sanitizer] 看板端口 {db_port} 已被其他程序占用。")
        print(f"[llm-sanitizer] 换端口启动: llm-sanitizer start --dashboard-port 8792")
        return
    gateway.init_state()
    try:
        gs = gateway.create_gateway_server(port=gw_port)
        ds = dashboard.create_dashboard_server(port=db_port)
    except OSError as e:
        print(f"[llm-sanitizer] 启动失败:端口不可用({e}).")
        print(f"[llm-sanitizer] 换端口启动: llm-sanitizer start --port 8792")
        return
    threading.Thread(target=gs.serve_forever, daemon=True).start()
    threading.Thread(target=ds.serve_forever, daemon=True).start()
    print(f"[llm-sanitizer] 网关  http://127.0.0.1:{gw_port}/v1")
    print(f"[llm-sanitizer] 看板  http://127.0.0.1:{db_port}")
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


def cmd_audit_export(args):
    """审计导出(v0.5):事件全量(主+.1)→ CSV/JSON,只含占位符无明文。
    供律所/组织合规留档;--since 按事件日期过滤;输出权限 600。"""
    import csv
    import time as _time

    from llm_sanitizer.events import read_all_events, read_stats_file

    events = read_all_events(str(config.events_path()))
    since_ts = None
    if args.since:
        try:
            since_ts = _time.mktime(_time.strptime(args.since, "%Y-%m-%d"))
        except ValueError:
            print(f"[llm-sanitizer] 无效日期: {args.since}(格式 YYYY-MM-DD)")
            return 1
    # 事件 ts 自 v0.5 起含日期(YYYY-MM-DD HH:MM:SS);旧格式(仅 HH:MM:SS)视为当日
    filtered = []
    for e in events:
        ts = str(e.get("ts", ""))
        if since_ts is not None:
            day = ts[:10]
            try:
                if _time.mktime(_time.strptime(day, "%Y-%m-%d")) < since_ts:
                    continue
            except ValueError:
                continue  # 旧格式无日期,审计导出时跳过(--since 场景)
        filtered.append(e)
    dest = Path(args.output) if args.output else config.data_dir() / f"audit_{_time.strftime('%Y%m%d')}"
    stats = read_stats_file(config.events_path())
    summary = {
        "total_events": len(filtered),
        "total_masked": stats.get("total_masked", 0),
        "total_requests": stats.get("total_requests", 0),
        "by_category": stats.get("by_category", {}),
        "exported_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "since": args.since or "all",
        "note": "事件仅含占位符/类别/时间/请求路径,不含明文(map.json 除外)",
    }
    if args.json:
        data = {"summary": summary, "events": filtered}
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        if not args.output:
            dest = dest.with_suffix(".json")
    else:
        import io

        buf = io.StringIO()
        header = ["ts", "kind", "category", "token", "method", "path"]
        writer = csv.writer(buf)
        writer.writerow(header)
        for e in filtered:
            writer.writerow([
                e.get("ts", ""), e.get("kind", ""), e.get("category", ""),
                e.get("token", ""), e.get("method", ""), e.get("path", ""),
            ])
        payload = buf.getvalue().encode("utf-8")
        if not args.output:
            dest = dest.with_suffix(".csv")
    # 原子写 + 600(审计文件含请求路径,可能敏感)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent or "."), prefix=".audit-")
    except OSError as e:
        print(f"[llm-sanitizer] 无法写入 {dest}:{e}")
        return 1
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    print(f"[ok] 审计已导出 {dest}({len(filtered)} 条事件,权限 600)")
    if args.json:
        print(f"  汇总:脱敏 {summary['total_masked']} 项 / 请求 {summary['total_requests']} 次")
    return 0


def cmd_desktop(args):
    """桌面轻包:原生窗口打开控制台(需 [desktop] extra)。"""
    from llm_sanitizer import desktop

    if not desktop.available():
        print("[llm-sanitizer] 桌面窗口是可选功能,当前未安装依赖:")
        print(desktop.install_hint())
        return 1
    return 0 if desktop.run() else 1


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
    p_start = sub.add_parser("start", help="前台启动网关与看板")
    p_start.add_argument("--port", type=int, help="网关端口(默认 8790)")
    p_start.add_argument("--dashboard-port", type=int, help="看板端口(默认 8791)")
    sub.add_parser("desktop", help="桌面窗口模式(需 pip install llm-sanitizer-gateway[desktop])")
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
    p_aud = sub.add_parser("audit-export", help="导出审计记录(CSV/JSON,只含占位符)")
    p_aud.add_argument("-o", "--output", help="输出文件(默认 <数据目录>/audit_日期.csv|.json)")
    p_aud.add_argument("--since", help="只导出该日期(含)之后的事件,格式 YYYY-MM-DD")
    p_aud.add_argument("--json", action="store_true", help="输出 JSON(含汇总)而非 CSV")
    p_con = sub.add_parser("connect", help="一键接入 Agent(当前支持 codex)")
    p_con.add_argument("agent")
    p_dis = sub.add_parser("disconnect", help="一键还原 Agent 配置")
    p_dis.add_argument("agent")
    args = ap.parse_args()
    if args.cmd == "start":
        cmd_start(args)
    elif args.cmd == "desktop":
        return cmd_desktop(args)
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
    elif args.cmd == "audit-export":
        return cmd_audit_export(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
