"""Regression tests for conservative number normalization."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voiceime_numbers import ContextNumberNormalizer  # noqa: E402


class ContextNumberNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.n = ContextNumberNormalizer()

    def test_explicit_digit_contexts(self):
        cases = {
            "user_id等于一二三四五": "user_id等于12345",
            "里面包含中文 English words 数字四二以及停顿": (
                "里面包含中文 English words 数字42以及停顿"
            ),
            "订单编号abc横杠二零二六下划线test": (
                "订单编号abc横杠2026下划线test"
            ),
            "版本号v一点三点七": "版本号v1.3.7",
            "版本号是 v 一点三点七": "版本号是 v 1.3.7",
            "价格是十九点九九美元": "价格是19.99美元",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.n.correct(source), expected)

    def test_natural_chinese_numbers_are_unchanged(self):
        cases = [
            "二零二六年九月二十一日",
            "请记录三个数字分别是负十一点五和三千零八",
            "我今天写了大约一千二百字",
            "准确率希望能达到百分之九十九",
            "大概十次里面会复现两到三次",
            "设置为零再重新启动服务",
            "连续录三十条样本然后用独立的十条样本做验收",
            "明天上午十点半",
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(self.n.correct(source), source)

    def test_malformed_or_unrelated_context_is_unchanged(self):
        self.assertEqual(self.n.correct("数字测试"), "数字测试")
        self.assertEqual(self.n.correct("等于一"), "等于一")
        self.assertEqual(self.n.correct("版本号v一点x"), "版本号v一点x")
        self.assertEqual(self.n.correct("价格十九点九x美元"), "价格十九点九x美元")


if __name__ == "__main__":
    unittest.main()
