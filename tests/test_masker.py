"""masker 规则引擎单元测试:命中/误报/一致性/持久化/开关/并发。"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_sanitizer.masker import Masker, mask_text, restore_text

# 命中样例:(文本, 期望类别)
HIT_CASES = [
    ("身份证 110101199001011234", "身份证号"),
    ("老证 110101900101123", "身份证号"),
    ("信用代码 91310000MA1FL1XW3U", "统一社会信用代码"),
    ("手机 13912345678", "手机号"),
    ("座机 021-12345678", "座机号"),
    ("邮箱 zhangsan@example.com", "邮箱"),
    ("银行卡 4111111111111111", "银行账号"),
    ("车牌 粤B12345", "车牌号"),
    ("新能源车 京A123456", "车牌号"),
    ("案号（2026）京01民初123号", "案号"),
    ("护照 E12345678", "证件号"),
    ("密钥 sk-abcdefghijklmnopqrstuvwxyz1234", "密钥令牌"),
    ("配置 api_key: sk-abcdefghijklmnopqrstuvwxyz1234", "密钥令牌"),
    ("公司 深圳市腾讯计算机系统有限公司", "公司名称"),
    ("法院 北京市海淀区人民法院", "司法机关"),
    ("仲裁 深圳仲裁委员会", "司法机关"),
    ("出生日期:1990年1月1日", "出生日期"),
    ("住址:广东省深圳市南山区科技园路1号", "地址"),
    ("原告张三 被告李四 法定代表人王五", "姓名"),
]

# 误报样例:必须原文保留
FP_CASES = [
    "被告认为该合同无效",
    "原告请求法院支持其主张",
    "公司认为该条款显失公平",
    "人民法院认为事实清楚",
    "这是编号123456789012345678测试",
    "请拨打010 或联系客服",
    "项目编号 6222021234",
    "地址：请前往前台办理",
    "案号格式是（2026）x01民初1号的示例",
]


class TestRules(unittest.TestCase):
    def test_hits(self):
        for text, cat in HIT_CASES:
            with self.subTest(text=text):
                masked, m = mask_text(text)
                self.assertTrue(
                    any(cat in t for t in m.mapping), f"{cat} 未命中: {text} -> {masked}"
                )
                self.assertNotIn("张三", masked)
                self.assertNotIn("13912345678", masked)

    def test_false_positives(self):
        for text in FP_CASES:
            with self.subTest(text=text):
                masked, _ = mask_text(text)
                self.assertEqual(masked, text, f"误报: {text} -> {masked}")

    def test_token_stability(self):
        text = "原告张三 电话13912345678"
        m1 = Masker()
        a, _ = mask_text(text, m1)
        b, _ = mask_text(text, m1)
        self.assertEqual(a, b, "同一 Masker 重复脱敏占位符应一致")

    def test_restore_roundtrip(self):
        sample = "原告张三 电话13912345678 住址:北京市朝阳区建国路88号"
        masked, m = mask_text(sample)
        restored = restore_text(masked, m.mapping)
        self.assertEqual(restored, sample)

    def test_persistence(self):
        sample = "原告张三 电话13912345678"
        _, m1 = mask_text(sample)
        m2 = Masker()
        m2.load_mapping(m1.mapping)
        a, _ = mask_text(sample, m2)
        b, _ = mask_text(sample, m1)
        self.assertEqual(a, b, "恢复映射后占位符不应漂移")

    def test_save_permissions(self):
        text = "原告张三"
        _, m = mask_text(text)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "map.json")
            m.save(path)
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600, f"map.json 权限应为 600,实际 {oct(mode)}")
            # 可重新加载
            m2 = Masker()
            with open(path, encoding="utf-8") as f:
                import json

                m2.load_mapping(json.load(f))
            a, _ = mask_text(text, m2)
            self.assertIn("[姓名_", a)

    def test_category_toggle(self):
        m = Masker(disabled_categories={"手机号"})
        masked, _ = mask_text("电话13912345678", m)
        self.assertIn("13912345678", masked, "禁用手机号后不应脱敏")
        masked2, _ = mask_text("电话13912345678")
        self.assertNotIn("13912345678", masked2)

    def test_concurrent_masking(self):
        """多线程并发脱敏:不崩溃、同一原文 token 一致。"""
        m = Masker()
        errors = []

        def work():
            try:
                for _ in range(50):
                    mask_text("原告张三 电话13912345678 住址:北京市朝阳区建国路88号", m)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertFalse(errors, f"并发脱敏异常: {errors}")
        self.assertEqual(m.mapping["[姓名_1]"], "张三")
        self.assertEqual(m.mapping["[手机号_1]"], "13912345678")


if __name__ == "__main__":
    unittest.main()
