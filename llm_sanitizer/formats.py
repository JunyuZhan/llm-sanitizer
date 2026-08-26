"""格式处理器(v0.2):docx / xlsx 保留格式脱敏与还原(纯标准库)。

设计(见 docs/开发文档.md §8):
- docx / xlsx 本质是 ZIP 包,正文是 XML;只改写文本节点
  (docx:`<w:t>`、`<w:delText>`;xlsx:`<t>`),标签与样式原样保留。
- 文本节点内容先 XML 反转义 → 脱敏/还原 → 再转义写回,不破坏结构。
- 供 CLI `mask` / `restore` 按扩展名分发;亦是"先脱敏文件再交 Agent"的
  辅助链路(与网关文本脱敏形成双保险)。
- PDF:纯标准库文本提取不可靠,暂不内置(v0.3 评估),文档如实标注。
"""

from __future__ import annotations

import re
import zipfile
import xml.sax.saxutils as sax

from .masker import mask_text, restore_text

# docx 文本节点: <w:t ...>text</w:t>、<w:delText ...>text</w:delText>
# xlsx 文本节点: <t ...>text</t>(sharedStrings 与内联字符串)
_TAG_RE = re.compile(
    r"<(?P<tag>w:t|w:delText|t)(?P<attrs>[^>]*)>(?P<text>.*?)</(?P=tag)>", re.S
)

_ZIP_SUFFIXES = (".docx", ".xlsx")


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
    """保留格式脱敏 docx/xlsx;返回改动的 XML 条目数。masker 可复用映射。"""
    return _transform_zip(src, dest, lambda t: mask_text(t, masker)[0])


def restore_file(src, dest, mapping) -> int:
    """用映射还原已脱敏的 docx/xlsx;返回改动的 XML 条目数。"""
    return _transform_zip(src, dest, lambda t: restore_text(t, mapping))
