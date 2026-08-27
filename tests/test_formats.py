"""格式处理器单元测试:docx/xlsx/pdf 保留格式脱敏/还原(v0.2+/v0.3)。

构造最小 docx/xlsx/pdf(ZIP+XML / FlateDecode stream),断言:文本被替换、
XML 结构与属性(如 xml:space)完好、PDF /Length 更新且还原后与原文一致。
"""

import os
import re
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_sanitizer import formats
from llm_sanitizer.masker import Masker

DOCX_DOC = (
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>原告张三 电话13912345678</w:t></w:r>"
    '<w:r><w:t xml:space="preserve"> 住址:北京市朝阳区建国路88号</w:t></w:r>'
    "</w:p></w:body></w:document>"
)

XLSX_SST = (
    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">'
    "<si><t>原告张三</t></si><si><t>电话 13912345678</t></si>"
    "</sst>"
)


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)


def _docx_entries():
    return {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        "word/document.xml": DOCX_DOC,
    }


def _xlsx_entries():
    return {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        "xl/sharedStrings.xml": XLSX_SST,
    }


def _read_zip(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


class TestFormats(unittest.TestCase):
    def test_docx_mask_preserves_structure(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.docx")
            dst = os.path.join(d, "masked.docx")
            _make_zip(src, _docx_entries())
            masker = Masker()
            changed = formats.mask_file(src, dst, masker)
            self.assertGreater(changed, 0)
            xml = _read_zip(dst, "word/document.xml")
            self.assertIn("[姓名_1]", xml)
            self.assertIn("[手机号_1]", xml)
            self.assertIn("[地址_1]", xml)
            self.assertNotIn("张三", xml)
            self.assertNotIn("13912345678", xml)
            # 结构与属性完好
            self.assertIn("<w:t>", xml)
            self.assertIn('xml:space="preserve"', xml)
            self.assertIn("</w:document>", xml)
            # 标签不残留占位符(占位符只在文本节点内)
            self.assertNotIn("<[姓名", xml)

    def test_docx_restore_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.docx")
            masked_p = os.path.join(d, "masked.docx")
            restored_p = os.path.join(d, "restored.docx")
            _make_zip(src, _docx_entries())
            masker = Masker()
            formats.mask_file(src, masked_p, masker)
            formats.restore_file(masked_p, restored_p, masker.mapping)
            self.assertEqual(_read_zip(restored_p, "word/document.xml"), DOCX_DOC,
                             "还原后 XML 应与原文逐字节一致")

    def test_xlsx_mask_shared_strings(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.xlsx")
            dst = os.path.join(d, "masked.xlsx")
            _make_zip(src, _xlsx_entries())
            masker = Masker()
            formats.mask_file(src, dst, masker)
            xml = _read_zip(dst, "xl/sharedStrings.xml")
            self.assertIn("[姓名_1]", xml)
            self.assertIn("[手机号_1]", xml)
            self.assertNotIn("张三", xml)
            self.assertNotIn("13912345678", xml)
            self.assertIn("<si>", xml)  # 结构完好
            restored = formats.restore_file(dst, os.path.join(d, "r.xlsx"), masker.mapping)
            self.assertGreater(restored, 0)
            self.assertEqual(_read_zip(os.path.join(d, "r.xlsx"), "xl/sharedStrings.xml"), XLSX_SST)

    def test_is_zip_doc(self):
        self.assertTrue(formats._is_zip_doc("a.DOCX"))
        self.assertTrue(formats._is_zip_doc("b.xlsx"))
        self.assertFalse(formats._is_zip_doc("c.txt"))
        self.assertFalse(formats._is_zip_doc("d.pdf"))

    def test_non_text_xml_untouched(self):
        """没有文本节点的条目应原样保留(如 content types)。"""
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.docx")
            dst = os.path.join(d, "masked.docx")
            _make_zip(src, _docx_entries())
            formats.mask_file(src, dst, Masker())
            ct = _read_zip(dst, "[Content_Types].xml")
            self.assertIn("content-types", ct)

    def test_pdf_mask_and_restore(self):
        """v0.3:PDF FlateDecode stream 文本替换、/Length 更新、还原一致。"""
        content = "BT /F1 12 Tf 72 720 Td (电话 13912345678) Tj ET".encode("utf-8")
        comp = zlib.compress(content)
        pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"2 0 obj\n<< /Type /Page /Parent 1 0 R /Contents 3 0 R >>\nendobj\n"
            b"3 0 obj\n<< /Length " + str(len(comp)).encode() + b" /Filter /FlateDecode >>\n"
            b"stream\n" + comp + b"\nendstream\nendobj\n"
            b"trailer\n<< /Root 1 0 R >>\n%%EOF"
        )
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.pdf")
            dst = os.path.join(d, "masked.pdf")
            rest = os.path.join(d, "restored.pdf")
            Path(src).write_bytes(pdf)
            masker = Masker()
            changed = formats.mask_file(src, dst, masker)
            self.assertGreater(changed, 0, "PDF 应有流被改动")
            data = Path(dst).read_bytes()
            # stream 解压后含占位符(非 ASCII 以 PDF 八进制转义表示)、无明文
            m = re.search(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S)
            self.assertIsNotNone(m)
            dec = zlib.decompress(m.group(1))
            self.assertIn(formats._pdf_escape("[手机号_1]"), dec)
            self.assertNotIn(b"13912345678", dec)
            # /Length 已更新为新流长度
            self.assertIn(b"/Length " + str(len(m.group(1))).encode(), data)
            # 还原后文本语义与原文一致(PDF 转义形式可能不同,比较解码后文本)
            formats.restore_file(dst, rest, masker.mapping)
            rdata = Path(rest).read_bytes()
            rm = re.search(rb"stream\r?\n(.*?)\r?\nendstream", rdata, re.S)
            restored_text = formats._pdf_unescape(zlib.decompress(rm.group(1)))
            self.assertIn("电话", restored_text)
            self.assertIn("13912345678", restored_text)

    def test_pdf_indirect_length_skipped(self):
        """v0.3:/Length 为间接引用(3 0 R)时跳过,不改动。"""
        comp = zlib.compress(b"BT (13912345678) Tj ET")
        pdf = (
            b"%PDF-1.4\n"
            b"3 0 obj\n<< /Length 4 0 R /Filter /FlateDecode >>\n"
            b"stream\n" + comp + b"\nendstream\nendobj\n"
            b"4 0 obj\n" + str(len(comp)).encode() + b"\nendobj\n"
            b"trailer\n<< >>\n%%EOF"
        )
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.pdf")
            dst = os.path.join(d, "masked.pdf")
            Path(src).write_bytes(pdf)
            changed = formats.mask_file(src, dst, Masker())
            self.assertEqual(changed, 0, "间接引用 /Length 应跳过")
            self.assertEqual(Path(dst).read_bytes(), pdf)


if __name__ == "__main__":
    unittest.main()
