"""Tests for deterministic VoiceIME domain-glossary correction."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voiceime_glossary import GlossaryCorrector  # noqa: E402


class GlossaryCorrectorTests(unittest.TestCase):
    def setUp(self):
        self.c = GlossaryCorrector([
            "pull request",
            "GitHub Actions",
            "updateSession",
            "systemd",
            "VS Code",
            "FinalRecognizer",
            "endpoint triggered",
            "user_id",
            "VOICEIME_ENABLE_LLM",
            "ONNX",
            "Stripe",
            "Linear",
            "Vercel",
            "AWS",
            "Henry Schein",
            "Darby Dental",
            "DC Dental",
        ])

    def test_real_sample_programming_corrections(self):
        cases = {
            "看一下 poll request 和 get help actions": (
                "看一下 pull request 和 GitHub Actions"
            ),
            "这个函数叫 update sesion": "这个函数叫 updateSession",
            "重新启动 system d 用户服务": "重新启动 systemd 用户服务",
            "打开 vs code 搜索 final recognizer": (
                "打开 VS Code 搜索 FinalRecognizer"
            ),
            "日志里看到 end point trigger red": "日志里看到 endpoint triggered",
            "调用 o n n x": "调用 ONNX",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.c.correct(source), expected)

    def test_dental_and_work_brand_corrections(self):
        cases = {
            "Dabby Dental 的价格": "Darby Dental 的价格",
            "Henry Shine 上有货": "Henry Schein 上有货",
            "stripe webhook": "Stripe webhook",
            "linear ticket": "Linear ticket",
            "vercel deployment": "Vercel deployment",
            "aws lambda": "AWS lambda",
            "DC Dental": "DC Dental",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.c.correct(source), expected)

    def test_never_changes_chinese(self):
        source = "今天中文识别已经很好了，重新启动 system d 服务"
        result = self.c.correct(source)
        self.assertEqual(
            "".join(ch for ch in result if "\u3400" <= ch <= "\u9fff"),
            "".join(ch for ch in source if "\u3400" <= ch <= "\u9fff"),
        )
        self.assertEqual(result, "今天中文识别已经很好了，重新启动 systemd 服务")

    def test_does_not_free_rewrite_unrelated_english(self):
        source = "please keep this completely ordinary sentence unchanged"
        self.assertEqual(self.c.correct(source), source)

    def test_short_acronyms_require_exact_match(self):
        self.assertEqual(self.c.correct("AR"), "AR")
        self.assertEqual(self.c.correct("PR"), "PR")

    def test_numbers_are_not_rewritten(self):
        source = "版本 v1.3.7 价格 19.99 user 12345"
        self.assertEqual(self.c.correct(source), source)


if __name__ == "__main__":
    unittest.main()
