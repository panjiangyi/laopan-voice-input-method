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


if __name__ == "__main__":
    unittest.main()
