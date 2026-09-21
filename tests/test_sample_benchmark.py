"""Tests for sample benchmark metrics."""
import runpy
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "scripts/15-evaluate-samples.py"))


class SampleBenchmarkTests(unittest.TestCase):
    def test_chinese_reordering_is_penalized(self):
        edits, total = M["cjk_error"]("我喜欢你", "你喜欢我")
        self.assertGreater(edits, 0)
        self.assertEqual(total, 4)

    def test_code_symbols_are_part_of_content_metric(self):
        self.assertGreater(M["content_error"]("版本1.5", "版本15")[0], 0)
        self.assertGreater(M["content_error"]("user_id", "userid")[0], 0)
        self.assertGreater(M["content_error"]("C++", "C")[0], 0)

    def test_punctuation_is_measured_separately(self):
        self.assertEqual(M["content_error"]("你好，世界。", "你好世界")[0], 0)
        edits, total = M["punctuation_error"]("你好，世界。", "你好世界")
        self.assertEqual(edits, 2)
        self.assertEqual(total, 2)

    def test_hybrid_rejects_fire_red_when_ascii_tokens_change(self):
        choose = M["choose_hybrid"]
        text, reason = choose(
            "打开 vs code 搜索 final recognizer",
            "打开S COAT搜索 FINCOGONNZER",
        )
        self.assertEqual(text, "打开 vs code 搜索 final recognizer")
        self.assertEqual(reason, "streaming-protected-ascii")

    def test_hybrid_allows_case_only_ascii_and_chinese_recovery(self):
        choose = M["choose_hybrid"]
        text, reason = choose(
            "这个 bug 偶尔出现大概十次里会浮现两到",
            "这个 BUG偶尔出现大概十次里会复现两到三次",
        )
        self.assertEqual(text, "这个 BUG偶尔出现大概十次里会复现两到三次")
        self.assertEqual(reason, "fire-red")

    def test_token_recall_requires_literal_technical_tokens(self):
        tokens = M["extract_tokens"](M["TOKEN_RE"], "GitHub Actions 和 user_id")
        hits, total = M["token_hits"](tokens, "github actions 和 userid")
        self.assertLess(hits, total)


if __name__ == "__main__":
    unittest.main()
