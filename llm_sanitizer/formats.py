"""格式处理器(v0.2+):docx / xlsx / pdf 保留格式脱敏与还原(纯标准库)。

设计(见 docs/开发文档.md §8):
- docx / xlsx 本质是 ZIP 包,正文是 XML;只改写文本节点
  (docx:`<w:t>`、`<w:delText>`;xlsx:`<t>`),标签与样式原样保留。
- PDF(v0.3):对 FlateDecode 压缩的 content stream 解压,替换文本操作符
  (`(…) Tj`、`[(…) (…)] TJ`),重压缩并更新 `/Length`(仅直接长度;
  间接引用对象跳过)。**局限如实标注**:文本可能被拆成多个片段(跨片段
  拼接不做),上下文型规则(姓名/地址)受限;格式规则(手机/身份证/邮箱/
  银行卡等)有效;扫描件(无文本层)无法处理。
- 供 CLI `mask` / `restore` 按扩展名分发;亦是"先脱敏文件再交 Agent"的
  辅助链路(与网关文本脱敏形成双保险)。
"""

from __future__ import annotations

import re
import zipfile
import zlib
import xml.sax.saxutils as sax
from pathlib import Path

from .masker import mask_text, restore_text

# docx 文本节点: <w:t ...>text</w:t>、<w:delText ...>text</w:delText>
# xlsx 文本节点: <t ...>text</t>(sharedStrings 与内联字符串)
_TAG_RE = re.compile(
    r"<(?P<tag>w:t|w:delText|t)(?P<attrs>[^>]*)>(?P<text>.*?)</(?P=tag)>", re.S
)

_ZIP_SUFFIXES = (".docx", ".xlsx")
_PDF_SUFFIX = ".pdf"

# PDF:带 /Length 直接长度的对象流(间接引用 /Length N 0 R 跳过)
_PDF_OBJ = re.compile(
    rb"<<(?P<dict>[^>]*?)>>\s*stream\r?\n(?P<data>.*?)\r?\nendstream", re.S
)
_PDF_LENGTH = re.compile(rb"/Length\s+(\d+)")
_PDF_LENGTH_INDIRECT = re.compile(rb"/Length\s+\d+\s+0\s+R")
# 文本操作符:(...) Tj 或 [(...) (...)] TJ
_PDF_TEXT_OP = re.compile(rb"\((?:\\.|[^\\()])*\)\s*Tj|\[(?:\((?:\\.|[^\\()])*\)\s*)+\]TJ")
_PDF_STR = re.compile(rb"\((?:\\.|[^\\()])*\)")


def supports(path: str) -> bool:
    """CLI 分发的支持集合:docx / xlsx / pdf。"""
    low = path.lower()
    return low.endswith(_ZIP_SUFFIXES) or low.endswith(_PDF_SUFFIX)


def _is_zip_doc(path: str) -> bool:
    return path.lower().endswith(_ZIP_SUFFIXES)


def _transform_xml(xml_bytes: bytes, fn) -> bytes:
    """对 XML 中所有文本节点应用 fn(脱敏或还原),结构与样式不动。"""
    text = xml_bytes.decode("utf-8")

    def repl(m):
        inner = m.group("text")
        if not inner:
            return m.group(0)
        plain = sax.unescape(inner)
        out = fn(plain)
        if out == plain:
            return m.group(0)
        return "<{0}{1}>{2}</{0}>".format(m.group("tag"), m.group("attrs"), sax.escape(out))

    return _TAG_RE.sub(repl, text).encode("utf-8")


def _transform_zip(src, dest, fn) -> int:
    """复制 ZIP 包并对其中的 XML 条目应用 fn;返回改动条目数。"""
    changed = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".xml"):
                new_data = _transform_xml(data, fn)
                if new_data != data:
                    changed += 1
                    data = new_data
            zout.writestr(item, data)
    return changed


def mask_file(src, dest, masker=None) -> int:
    """保留格式脱敏 docx/xlsx/pdf;返回改动的流/条目数。masker 可复用映射。"""
    if src.lower().endswith(_PDF_SUFFIX):
        return _transform_pdf_file(src, dest, lambda t: mask_text(t, masker)[0])
    return _transform_zip(src, dest, lambda t: mask_text(t, masker)[0])


def restore_file(src, dest, mapping) -> int:
    """用映射还原已脱敏的 docx/xlsx/pdf;返回改动的流/条目数。"""
    if src.lower().endswith(_PDF_SUFFIX):
        return _transform_pdf_file(src, dest, lambda t: restore_text(t, mapping))
    return _transform_zip(src, dest, lambda t: restore_text(t, mapping))


# ---------------------------------------------------------------------------
# PDF(v0.3,尽力而为)
# ---------------------------------------------------------------------------
def _pdf_unescape(b: bytes) -> str:
    r"""PDF 括号字符串反转义 → 文本(支持 \n \r \t \( \) \\ 与八进制)。"""
    out = bytearray()
    i = 0
    n = len(b)
    while i < n:
        c = b[i]
        if c == 0x5C and i + 1 < n:  # backslash
            x = b[i + 1]
            table = {0x6E: b"\n", 0x72: b"\r", 0x74: b"\t", 0x62: b"\b",
                     0x66: b"\f", 0x28: b"(", 0x29: b")", 0x5C: b"\\"}
            if x in table:
                out += table[x]
                i += 2
            elif 0x30 <= x <= 0x37:  # \ddd octal
                end = i + 1
                while end < n and end < i + 4 and 0x30 <= b[end] <= 0x37:
                    end += 1
                out += bytes([int(b[i + 1:end], 8) & 0xFF])
                i = end
            else:
                out += bytes([x])
                i += 2
        else:
            out += bytes([c])
            i += 1
    return out.decode("utf-8", "replace")


def _pdf_escape(s: str) -> bytes:
    """文本 → PDF 括号字符串(逐字节处理:()\\ 与 <32 或 >126 转 \\ddd 八进制)。

    PDF 八进制转义最多 3 位(\\377),必须按 UTF-8 字节而非 Unicode 码点转义,
    否则中文等会生成非法的 4+ 位转义,阅读器无法解码。
    """
    out = bytearray()
    for b in s.encode("utf-8"):
        if b in b"()\\":
            out += b"\\" + bytes([b])
        elif b < 32 or b > 126:
            out += ("\\%03o" % b).encode()
        else:
            out += bytes([b])
    return bytes(out)


def _transform_pdf_stream(content: bytes, fn) -> bytes:
    """对解压后的 content stream 中的文本操作符应用 fn。"""

    def repl_str(sm):
        raw = sm.group(0)[1:-1]
        text = _pdf_unescape(raw)
        out = fn(text)
        if out == text:
            return sm.group(0)
        return b"(" + _pdf_escape(out) + b")"

    def repl_op(m):
        return _PDF_STR.sub(repl_str, m.group(0))

    return _PDF_TEXT_OP.sub(repl_op, content)


def _transform_pdf_file(src, dest, fn) -> int:
    """处理所有可解压的 content stream;返回改动流数。

    仅处理 `/Length` 为直接数字的对象(间接引用无法安全改长度,跳过)。
    """
    data = Path(src).read_bytes()
    changed = 0

    def repl_obj(m):
        nonlocal changed
        d = m.group("dict")
        if _PDF_LENGTH_INDIRECT.search(d):
            return m.group(0)  # /Length N 0 R 间接引用,跳过
        lm = _PDF_LENGTH.search(d)
        if not lm:
            return m.group(0)
        raw = m.group("data")
        try:
            content = zlib.decompress(raw)
        except Exception:
            return m.group(0)  # 非 FlateDecode 或损坏
        new_content = _transform_pdf_stream(content, fn)
        if new_content == content:
            return m.group(0)
        new_raw = zlib.compress(new_content)
        changed += 1
        new_dict = d[: lm.start()] + b"/Length " + str(len(new_raw)).encode() + d[lm.end():]
        return b"<<" + new_dict + b">> stream\n" + new_raw + b"\nendstream"

    out = _PDF_OBJ.sub(repl_obj, data)
    if out != data:
        Path(dest).write_bytes(out)
    else:
        Path(dest).write_bytes(data)
    return changed
