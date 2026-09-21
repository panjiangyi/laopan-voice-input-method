"""Regression tests for the current ASR benchmark metrics."""
import runpy
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUITE = runpy.run_path(str(ROOT / "scripts/08-offline-suite.py"))


class BenchmarkMetricTests(unittest.TestCase):
    def test_reordered_sentence_is_not_100_percent(self):
        distance, rate = SUITE["cer"]("我喜欢你", "你喜欢我")
        self.assertGreater(distance, 0)
        self.assertGreater(rate, 0)

    def test_repetition_and_extra_chars_are_penalized(self):
        distance, rate = SUITE["cer"]("你好", "你好你好")
        self.assertEqual(distance, 2)
        self.assertEqual(rate, 1.0)

    def test_punctuation_is_cosmetic_but_code_symbols_are_not(self):
        self.assertEqual(SUITE["cer"]("你好世界", "你好，世界。"), (0, 0.0))
        self.assertGreater(SUITE["cer"]("版本1.5", "版本15")[0], 0)
        self.assertGreater(SUITE["cer"]("user_id", "userid")[0], 0)

    def test_raw_cer_counts_formatting(self):
        self.assertEqual(SUITE["raw_cer"]("你好。", "你好")[0], 1)

    def test_category_tokens_measure_english_and_numbers(self):
        token_distance = SUITE["token_distance"]
        self.assertEqual(token_distance(r"[a-z]+", "use GitHub", "use gitlab"), (1, 2))
        self.assertEqual(token_distance(r"\d+", "版本 123", "版本 12"), (1, 1))


if __name__ == "__main__":
    unittest.main()
