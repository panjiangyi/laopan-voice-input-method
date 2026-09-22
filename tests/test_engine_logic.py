"""Unit tests for the event-driven VoiceIME engine."""
import runpy
from pathlib import Path
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ENGINE = runpy.run_path(str(ROOT / "voiceime-engine"))


class FakeBridge:
    def __init__(self):
        self.calls = []

    def update(self, session, remove, text):
        self.calls.append((session, remove, text))
        return True


class ReconcilerTests(unittest.TestCase):
    def test_patch_corrects_only_changed_suffix(self):
        patch_fn = ENGINE["TextReconciler"].patch
        self.assertEqual(patch_fn("你好测式", "你好测试"), (1, "试"))
        self.assertEqual(patch_fn("hello wor", "hello world"), (0, "ld"))
        # Suffix walk stops at whitespace boundaries, so a space inserted
        # between CJK and Latin yields a pure-append insert, not a rewrite.
        self.assertEqual(patch_fn("今天review", "今天 review"), (0, " "))
        # Mid-string LLM-style rewrite: keep the (small) prefix and suffix,
        # only delete the mismatched middle so the native bridge accepts it.
        self.assertEqual(
            patch_fn("不是 l l m 浮现失败是 a s i 模型本身就有问",
                     "不是 LLM 浮现失败，是 ASI 模型本身就有问题"),
            (25, "LLM 浮现失败，是 ASI 模型本身就有问题"),
        )
        # Pure CJK middle edit keeps the prefix/suffix windows narrow.
        self.assertEqual(
            patch_fn("今天写作和编程", "今天协作和编程"),
            (1, "协"),
        )

    def test_force_final_correction_uses_session(self):
        cls = ENGINE["TextReconciler"]
        bridge = FakeBridge()
        r = cls(bridge, "session-1")
        r.emit("今天review这个PR", force=True)
        r.emit("今天 review 这个 PR", force=True)
        self.assertEqual(
            bridge.calls[0],
            ("session-1", 0, "今天review这个PR"),
        )
        self.assertGreater(bridge.calls[1][1], 0)


class FinalPaddingTests(unittest.TestCase):
    def test_finalize_supplies_configured_trailing_silence(self):
        class Stream:
            def __init__(self):
                self.samples = None

            def accept_waveform(self, _rate, samples):
                self.samples = samples

            def input_finished(self):
                pass

        class Recognizer:
            def is_ready(self, _stream):
                return False

            def get_result(self, _stream):
                return type("Result", (), {"text": "完成"})()

        asr = object.__new__(ENGINE["SherpaRecognizer"])
        asr.recognizer = Recognizer()
        stream = Stream()
        with patch.dict(asr.finalize.__globals__, FINAL_PADDING_SEC=1.0):
            self.assertEqual(asr.finalize(stream), "完成")
        self.assertEqual(len(stream.samples), 16000)
        self.assertTrue(np.all(stream.samples == 0))


class FinalRecognizerConfigTests(unittest.TestCase):
    def test_second_pass_can_be_explicitly_disabled(self):
        with patch.dict("os.environ", {"VOICEIME_FINAL_ENABLED": "0"}, clear=True):
            recognizer = ENGINE["FinalRecognizer"]()
        self.assertIsNone(recognizer.recognizer)
        self.assertFalse(recognizer.enabled)


class PreeditFinalTests(unittest.TestCase):
    class Identity:
        def correct(self, text):
            return text

    def test_queued_next_utterance_skips_final_wait(self):
        calls = []

        class Final:
            recognizer = object()
            def transcribe(self, _pcm):
                calls.append("final")
                return "不应该运行"

        class Glossary:
            def correct(self, text):
                return text.replace("system d", "systemd")

        class Punctuation:
            def correct(self, text):
                return text + "。"

        fn = ENGINE["_best_final_text"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.dict(
                fn.__globals__,
                current_session="s1",
                start_request=2,
                FINAL_MAX_WAIT_SEC=1.2,
                FINAL_MAX_AUDIO_SEC=10.0,
                final_inflight=None,
            ):
                result = fn(
                    "s1", 1, "重启 system d", b"x" * 32000,
                    Final(), Glossary(), self.Identity(), Punctuation(), executor,
                )
        self.assertEqual(result, "重启 systemd。")
        self.assertEqual(calls, [])

    def test_long_utterance_skips_offline_final(self):
        calls = []

        class Final:
            recognizer = object()
            def transcribe(self, _pcm):
                calls.append("final")
                return "不应该运行"

        class Identity:
            def correct(self, text):
                return text

        fn = ENGINE["_best_final_text"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.dict(
                fn.__globals__,
                current_session="s1",
                start_request=1,
                FINAL_MAX_WAIT_SEC=1.2,
                FINAL_MAX_AUDIO_SEC=1.0,
                final_inflight=None,
            ):
                result = fn(
                    "s1", 1, "长句实时结果", b"x" * (16000 * 2 * 2),
                    Final(), Identity(), Identity(), Identity(), executor,
                )
        self.assertEqual(result, "长句实时结果")
        self.assertEqual(calls, [])

    def test_busy_final_worker_never_queues_another_job(self):
        from concurrent.futures import Future

        busy = Future()
        calls = []

        class Final:
            recognizer = object()
            def transcribe(self, _pcm):
                calls.append("final")
                return "不应该排队"

        class Identity:
            def correct(self, text):
                return text

        fn = ENGINE["_best_final_text"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.dict(
                fn.__globals__,
                current_session="s2",
                start_request=2,
                FINAL_MAX_WAIT_SEC=1.2,
                FINAL_MAX_AUDIO_SEC=10.0,
                final_inflight=busy,
            ):
                result = fn(
                    "s2", 2, "第二句实时结果", b"x" * 32000,
                    Final(), Identity(), Identity(), Identity(), executor,
                )
        self.assertEqual(result, "第二句实时结果")
        self.assertEqual(calls, [])

    def test_number_normalization_runs_before_punctuation(self):
        class Final:
            recognizer = object()
            def transcribe(self, _pcm):
                return "版本号v一点三点七价格是十九点九九美元"

        class Identity:
            def correct(self, text):
                return text

        class Numbers:
            def correct(self, text):
                return text.replace(
                    "v一点三点七价格是十九点九九美元",
                    "v1.3.7价格是19.99美元",
                )

        class Punctuation:
            def correct(self, text):
                return text + "。"

        fn = ENGINE["_best_final_text"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.dict(
                fn.__globals__,
                current_session="s1",
                start_request=1,
                FINAL_MAX_WAIT_SEC=1.2,
                FINAL_MAX_AUDIO_SEC=10.0,
                final_inflight=None,
            ):
                result = fn(
                    "s1", 1, "版本号实时结果", b"x" * 32000,
                    Final(), Identity(), Numbers(), Punctuation(), executor,
                )
        self.assertEqual(result, "版本号v1.3.7价格是19.99美元。")

    def test_fast_final_is_glossary_corrected_before_commit(self):
        class Final:
            recognizer = object()
            def transcribe(self, _pcm):
                return "看一下 poll request"

        class Glossary:
            def correct(self, text):
                return text.replace("poll request", "pull request")

        class Punctuation:
            def correct(self, text):
                return text + "。"

        fn = ENGINE["_best_final_text"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch.dict(
                fn.__globals__,
                current_session="s1",
                start_request=1,
                FINAL_MAX_WAIT_SEC=1.2,
                FINAL_MAX_AUDIO_SEC=10.0,
                final_inflight=None,
            ):
                result = fn(
                    "s1", 1, "看一下破 request", b"x" * 32000,
                    Final(), Glossary(), self.Identity(), Punctuation(), executor,
                )
        self.assertEqual(result, "看一下 pull request。")


class SignalRequestTests(unittest.TestCase):
    def test_release_for_queued_press_is_not_lost(self):
        on_start = ENGINE["on_start"]
        on_finish = ENGINE["on_finish"]
        with patch.dict(
            on_start.__globals__, start_request=1, stop_request=1
        ):
            on_start(None, None)
            on_finish(None, None)
            self.assertEqual(on_start.__globals__["start_request"], 2)
            self.assertEqual(on_start.__globals__["stop_request"], 2)


class AsyncRefinementTests(unittest.TestCase):
    def test_second_pass_exception_falls_back_to_streaming_text(self):
        calls = []

        class BrokenFinal:
            def transcribe(self, _pcm):
                raise RuntimeError("inference exploded")

        class PunctuationOnly:
            def correct(self, text):
                return text + "。"

        class AsyncBridge:
            def update(self, session, remove, text):
                calls.append((session, remove, text))
                return True

        fn = ENGINE["refine_async"]
        with patch.dict(
            fn.__globals__,
            current_session="s1",
            FcitxBridge=AsyncBridge,
        ):
            fn("s1", "实时结果", b"x" * 32000, BrokenFinal(), PunctuationOnly())

        # FireRed failure must not abort the pipeline. The already-committed
        # streaming text remains the base and later safe refinement can append.
        self.assertEqual(calls, [("s1", 0, "。")])

    def test_stale_session_cancels_late_refinement(self):
        class ShouldNotRun:
            def transcribe(self, _pcm):
                raise AssertionError("stale job should self-cancel")

        fn = ENGINE["refine_async"]
        with patch.dict(fn.__globals__, current_session="new-session"):
            fn("old-session", "旧句", b"x" * 32000, ShouldNotRun(), ShouldNotRun())


if __name__ == "__main__":
    unittest.main()
