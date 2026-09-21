"""Unit tests for the event-driven VoiceIME engine."""
import runpy
from pathlib import Path
import unittest
from unittest.mock import patch
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
        self.assertEqual(patch_fn("今天review", "今天 review"), (6, " review"))

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
    def test_second_pass_is_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            recognizer = ENGINE["FinalRecognizer"]()
        self.assertIsNone(recognizer.recognizer)


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
