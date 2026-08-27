"""图片 OCR 脱敏单元测试(v0.4,可选特性)。

核心逻辑(mask_blocks / render_text / redact_image)是纯函数,不依赖
pytesseract / Pillow 即可测试;真机 tesseract 相关测试按可用性跳过。
"""

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_sanitizer import ocr  # noqa: E402
from llm_sanitizer.masker import Masker  # noqa: E402

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

# 模拟 tesseract 返回的文本块(身份证照片场景)
FAKE_BLOCKS = [
    ocr.OcrBlock(text="姓名 张三", bbox=(10, 10, 120, 20)),
    ocr.OcrBlock(text="身份证 110101199001011234", bbox=(10, 35, 260, 20)),
    ocr.OcrBlock(text="手机 13912345678", bbox=(10, 60, 200, 20)),
    ocr.OcrBlock(text="住址 北京市朝阳区建国路88号", bbox=(10, 85, 300, 20)),
]


class TestMaskBlocks(unittest.TestCase):
    def test_masked_and_changed_flags(self):
        """敏感块被脱敏、changed=True;非敏感块原样、changed=False。"""
        masked = ocr.mask_blocks(FAKE_BLOCKS, Masker())
        by_text = {b.text: b for b in masked}
        self.assertEqual(by_text["姓名 张三"].masked_text, "姓名 [姓名_1]")
        self.assertTrue(by_text["姓名 张三"].changed)
        self.assertIn("[身份证号_1]", by_text["身份证 110101199001011234"].masked_text)
        self.assertIn("[手机号_1]", by_text["手机 13912345678"].masked_text)
        self.assertIn("[地址_1]", by_text["住址 北京市朝阳区建国路88号"].masked_text)
        # bbox 原样保留(打码模式需要)
        self.assertEqual(by_text["姓名 张三"].bbox, (10, 10, 120, 20))

    def test_mapping_reuse(self):
        """复用 masker:同一原文 token 一致(与网关/文件链路互通)。"""
        m = Masker()
        ocr.mask_blocks(FAKE_BLOCKS, m)
        masked2 = ocr.mask_blocks([FAKE_BLOCKS[0]], m)
        self.assertEqual(masked2[0].masked_text, "姓名 [姓名_1]")

    def test_render_text_layout(self):
        """文本报告按视觉行拼接,还原可读布局。"""
        masked = ocr.mask_blocks(FAKE_BLOCKS, Masker())
        text = ocr.render_text(masked)
        self.assertIn("姓名 [姓名_1]", text)
        self.assertIn("[手机号_1]", text)
        lines = text.splitlines()
        # 每个块一行(bbox y 均不同,未聚合)
        self.assertEqual(len(lines), 4)

    def test_render_text_groups_same_row(self):
        """同一行的多个块(如姓名+出生日期并排)拼接进同一行。"""
        blocks = [
            ocr.OcrBlock(text="原告 张三", bbox=(10, 10, 100, 20)),
            ocr.OcrBlock(text="被告 李四", bbox=(200, 12, 100, 20)),  # y 差 2,同行
            ocr.OcrBlock(text="第三人 王五", bbox=(10, 50, 100, 20)),  # 新行
        ]
        text = ocr.render_text(ocr.mask_blocks(blocks, Masker()))
        lines = text.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("原告 [姓名_1] 被告 [姓名_2]", lines[0])
        self.assertIn("第三人 [姓名_3]", lines[1])


@unittest.skipUnless(HAS_PIL, "需要 Pillow(可选依赖)")
class TestRedactImage(unittest.TestCase):
    def test_redact_blackens_bbox(self):
        """打码:changed 块的 bbox 区域变黑,未覆盖区域保持原色。"""
        img = Image.new("RGB", (200, 100), (255, 255, 255))
        changed = [
            ocr.MaskedBlock("电话 13912345678", (50, 20, 100, 15),
                            "电话 [手机号_1]", True),
        ]
        out = ocr.redact_image(img, changed)
        # bbox 中心(含 pad)应为黑
        self.assertEqual(out.getpixel((100, 27)), (0, 0, 0))
        # 未覆盖区域仍白
        self.assertEqual(out.getpixel((5, 5)), (255, 255, 255))

    def test_redact_clips_at_bounds(self):
        """bbox 超出画布边界时裁剪不报错。"""
        img = Image.new("RGB", (100, 50), (255, 255, 255))
        changed = [
            ocr.MaskedBlock("x", (95, 45, 20, 20), "x", True),  # 超右下角
            ocr.MaskedBlock("y", (-5, -5, 10, 10), "y", True),  # 超左上角
        ]
        out = ocr.redact_image(img, changed)  # 不抛异常即可
        self.assertEqual(out.size, (100, 50))


@unittest.skipUnless(ocr.engine_available(), "本机未装 pytesseract/tesseract")
class TestRealEngine(unittest.TestCase):
    def test_engine_detect_returns_blocks(self):
        """真机冒烟:对 PIL 生成的简单图片执行 OCR(语言失败也应有结果或报错)。"""
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (300, 60), (255, 255, 255))
        ImageDraw.Draw(img).text((10, 15), "13912345678", fill=(0, 0, 0))
        tmp = os.path.join(tempfile_dir(), "ocr_smoke.png")
        img.save(tmp)
        eng = ocr.PytesseractEngine(lang="eng")
        try:
            blocks = eng.detect(tmp)
            self.assertIsInstance(blocks, list)
        except ocr.OcrError:
            self.fail("OCR 引擎应可用(engine_available=True)")
        finally:
            os.unlink(tmp)


def tempfile_dir():
    import tempfile

    return tempfile.mkdtemp(prefix="llmsan-ocr-")


class TestCliDispatch(unittest.TestCase):
    @unittest.skipIf(ocr.engine_available(), "本机已装 OCR,走真分支(由 TestRealEngine 覆盖)")
    def test_cli_prints_install_hint(self):
        """未装 [ocr] 依赖时,mask 图片给出友好安装提示(不崩溃)。"""
        tmp = os.path.join(tempfile_dir(), "card.png")
        with open(tmp, "wb") as f:
            f.write(b"not-a-real-png")
        r = subprocess.run(
            [sys.executable, "-m", "llm_sanitizer", "mask", tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        self.assertIn("[ocr]", r.stdout)
        self.assertIn("tesseract", r.stdout)
        os.unlink(tmp)

    def test_supports_extensions(self):
        self.assertTrue(ocr.supports("a.PNG"))
        self.assertTrue(ocr.supports("身份证.jpg"))
        self.assertFalse(ocr.supports("a.docx"))
        self.assertFalse(ocr.supports("a.txt"))


if __name__ == "__main__":
    unittest.main()
