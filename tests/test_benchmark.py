"""Regression tests for the current ASR benchmark metrics."""
import runpy
from pathlib import Path
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
SUITE = runpy.run_path(str(ROOT / "scripts/08-offline-suite.py"))


class BenchmarkMetricTests(unittest.TestCase):
    def test_benchmark_uses_production_duration_gate_and_postprocessing(self):
        class Streaming:
            def create_stream(self): return object()
            def accept_pcm(self, stream, pcm): pass
            def decode_ready(self, stream): pass
            def finalize(self, stream): return "poll request"

        class Final:
            recognizer = object()
            def transcribe(self, pcm):
                raise AssertionError("long recording must skip final")

        class Glossary:
            def correct(self, text): return text.replace("poll", "pull")

        class Punctuation:
            def correct(self, text): return text + "。"

        state = SUITE["ENGINE"]["_best_final_text"].__globals__
        with patch.dict(state, FINAL_MAX_AUDIO_SEC=0.5, final_inflight=None):
            with ThreadPoolExecutor(max_workers=1) as executor:
                raw, final = SUITE["recognize_current"](
                    Streaming(), Final(), bytes(32000), glossary=Glossary(),
                    punctuation=Punctuation(), executor=executor,
                )
        self.assertEqual(raw, "poll request")
        self.assertEqual(final, "pull request。")

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
