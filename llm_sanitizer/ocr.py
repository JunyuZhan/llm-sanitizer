"""图片 OCR 脱敏(v0.4,可选依赖特性)。

定位:与 docx/xlsx/pdf 同一"辅助链路"——先把身份证照片、合同扫描件等
图片里的文字 OCR 出来并脱敏,再交给 Agent,避免图片中的明文出网。

**为什么是可选特性(ADR-1 承诺不变)**:OCR 无法用纯标准库实现,需要
第三方库 + 系统二进制,故设计为:
    pip install llm-sanitizer-gateway[ocr]
    # 还需系统级 tesseract:brew install tesseract tesseract-lang
    #   / apt install tesseract-ocr tesseract-ocr-chi-sim / Windows 官方安装包
核心包不装任何 OCR 依赖,import 零开销。

设计:
- OcrEngine 抽象:`detect(image) -> list[OcrBlock]`(text + bbox),未来可换
  paddleocr / easyocr,业务层不变。
- 默认 `PytesseractEngine`(pytesseract + Pillow,延迟导入)。
- 双输出模式:
  * 文本报告(默认):OCR 文本按行布局还原 → 逐块脱敏 → `.txt`(**可还原**)
  * 打码图(`--redact`):在原图敏感区域涂黑 → 图片(不可逆,如实标注)
- 核心逻辑(mask_blocks / render_text / redact_image)是与引擎解耦的纯函数,
  不依赖 OCR 依赖即可单测。
"""

from __future__ import annotations

import os
import sys
from collections import namedtuple
from pathlib import Path

from .masker import Masker, mask_text

# (x, y, w, h)——tesseract image_to_data 的坐标系(左上原点)
OcrBlock = namedtuple("OcrBlock", ["text", "bbox"])
MaskedBlock = namedtuple("MaskedBlock", ["text", "bbox", "masked_text", "changed"])

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")

# 默认语言:中文简体 + 英文(tesseract 多语言用 + 拼接)
DEFAULT_LANG = "chi_sim+eng"


class OcrError(Exception):
    """OCR 不可用或处理失败。"""


class OcrUnavailable(OcrError):
    """未安装 [ocr] 可选依赖或系统 tesseract。"""


def supports(path: str) -> bool:
    """CLI 分发的图片扩展名集合。"""
    return path.lower().endswith(_IMAGE_SUFFIXES)


def engine_available() -> bool:
    """pytesseract + Pillow + 系统 tesseract 二进制三者齐备才可用。"""
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


class PytesseractEngine:
    """默认 OCR 引擎:tesseract(通过 pytesseract 调用),中文需 chi_sim 语言包。

    依赖延迟导入——核心包 import 本模块不会加载 pytesseract/Pillow。
    """

    def __init__(self, lang=None):
        import pytesseract  # 延迟导入,ADR-1 核心零依赖

        self._pt = pytesseract
        self.lang = lang or DEFAULT_LANG

    def detect(self, image_path) -> list:
        """OCR 识别,返回按出现顺序排列的 OcrBlock 列表(word 级,含坐标)。"""
        from PIL import Image  # 延迟导入

        img = Image.open(image_path)
        data = self._pt.image_to_data(img, lang=self.lang, output_type=self._pt.Output.DICT)
        blocks = []
        n = len(data.get("text") or [])
        for i in range(n):
            t = (data["text"][i] or "").strip()
            w = int(data["width"][i])
            h = int(data["height"][i])
            if not t or w <= 0 or h <= 0:
                continue
            blocks.append(OcrBlock(text=t, bbox=(int(data["left"][i]), int(data["top"][i]), w, h)))
        return blocks


def mask_blocks(blocks, masker=None) -> list:
    """对每个 OCR 块独立脱敏;返回 MaskedBlock 列表。masker 可复用映射。"""
    m = masker or Masker()
    out = []
    for blk in blocks:
        masked, _ = mask_text(blk.text, m)
        out.append(MaskedBlock(blk.text, blk.bbox, masked, masked != blk.text))
    return out


def merge_blocks(blocks) -> list:
    """把同一视觉行的块按 x 排序直接拼接成一个大块(v0.4.1)。

    动机:tesseract 常把中文拆成单字块("姓名:张三" → 姓/名/:/张/三),
    逐块脱敏会让姓名、地址等依赖连续文本的上下文规则全部落空。按行合并
    后文本恢复连续序列,规则重新命中;bbox 取并集(打码覆盖整行,更彻底)。
    注意:拼接会丢失词间空格(OCR 输出本就不含),对格式规则(手机号/身份
    证/邮箱)与"角色词+连续汉字"的姓名规则有利。
    """
    out = []
    for row in _group_lines(blocks):
        row_sorted = sorted(row, key=lambda b: b.bbox[0])
        text = "".join(b.text for b in row_sorted)
        x = min(b.bbox[0] for b in row_sorted)
        y = min(b.bbox[1] for b in row_sorted)
        w = max(b.bbox[0] + b.bbox[2] for b in row_sorted) - x
        h = max(b.bbox[1] + b.bbox[3] for b in row_sorted) - y
        out.append(OcrBlock(text=text, bbox=(x, y, w, h)))
    return out


def _group_lines(masked_blocks) -> list:
    """按 bbox 的 y 分桶成"视觉行"(同一行的块 top 差距小),行内按 x 排序。"""
    rows = []  # 每行: [block, ...]
    for b in sorted(masked_blocks, key=lambda b: (b.bbox[1], b.bbox[0])):
        if not rows:
            rows.append([b])
            continue
        last = rows[-1][-1]
        y = b.bbox[1]
        h_last = max(1, last.bbox[3])
        # 与当前行最后一块的 top 差 < 行高一半 → 视为同一行
        if y - last.bbox[1] < h_last / 2:
            rows[-1].append(b)
        else:
            rows.append([b])
    return rows


def render_text(masked_blocks) -> str:
    """把脱敏块还原成近似原布局的文本(行内空格拼接,行间换行)。"""
    return "\n".join(" ".join(b.masked_text for b in row) for row in _group_lines(masked_blocks))


def redact_image(pil_image, changed_blocks, fill=(0, 0, 0), pad=2):
    """在 changed 块的 bbox 处涂色块(默认黑色),返回新 PIL 图像。不可逆。"""
    from PIL import ImageDraw  # 延迟导入

    canvas = pil_image.convert("RGB")
    w, h = canvas.size
    draw = ImageDraw.Draw(canvas)
    for b in changed_blocks:
        x, y, bw, bh = b.bbox
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(w, x + bw + pad)
        y1 = min(h, y + bh + pad)
        draw.rectangle([x0, y0, x1, y1], fill=fill)
    return canvas


def mask_image(src, dest=None, masker=None, redact=False, lang=None) -> dict:
    """对图片 OCR 脱敏。返回 {\"mode\": \"text\"|\"redact\", \"changed\": int, \"dest\": str}。

    - redact=False:输出脱敏文本报告(.txt,可还原)
    - redact=True :输出打码图(敏感区域涂黑,不可逆)
    未安装 [ocr] 依赖 / tesseract 时抛 OcrUnavailable(CLI 层转友好提示)。
    """
    if not engine_available():
        raise OcrUnavailable(
            "OCR 功能需要可选依赖:\n"
            "  pip install llm-sanitizer-gateway[ocr]\n"
            "以及系统 tesseract:\n"
            "  macOS: brew install tesseract tesseract-lang\n"
            "  Ubuntu: apt install tesseract-ocr tesseract-ocr-chi-sim\n"
            "  Windows: 官方安装包(需含 chi_sim 语言包)"
        )
    engine = PytesseractEngine(lang)
    blocks = engine.detect(str(src))
    # 行内合并修复 tesseract 中文拆字(v0.4.1):姓名/地址等上下文规则重新命中
    merged = merge_blocks(blocks)
    masked = mask_blocks(merged, masker)
    changed = sum(1 for b in masked if b.changed)
    src_path = Path(src)

    if redact:
        from PIL import Image  # 延迟导入

        canvas = redact_image(Image.open(src_path), [b for b in masked if b.changed])
        out = Path(dest) if dest else src_path.with_name("redacted_" + src_path.name)
        canvas.save(out)
        return {"mode": "redact", "changed": changed, "dest": str(out)}

    text = render_text(masked)
    if dest:
        out = Path(dest)
    else:
        out = src_path.with_name("masked_" + src_path.stem + ".txt")
    out.write_text(text, encoding="utf-8")
    return {"mode": "text", "changed": changed, "dest": str(out)}


def install_hint() -> str:
    """未安装依赖时的安装指引(供 CLI / 控制台提示)。"""
    return (
        "图片 OCR 脱敏是可选功能,需要:\n"
        "  1. pip install llm-sanitizer-gateway[ocr]\n"
        "  2. 系统 tesseract(中文需 chi_sim 语言包):\n"
        "     macOS   brew install tesseract tesseract-lang\n"
        "     Ubuntu  sudo apt install tesseract-ocr tesseract-ocr-chi-sim\n"
        "     Windows 官方安装包: https://github.com/UB-Mannheim/tesseract/wiki"
    )
