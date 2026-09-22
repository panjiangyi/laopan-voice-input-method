"""Unit tests for the event-driven VoiceIME engine."""
import runpy
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
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
        # The bridge edits at the end of the preedit, so a middle change must
        # replace the complete tail rather than incorrectly preserving a
        # common suffix that cannot be reached by the cursor.
        self.assertEqual(
            patch_fn("不是 l l m 浮现失败是 a s i 模型本身就有问",
                     "不是 LLM 浮现失败，是 ASI 模型本身就有问题"),
            (25, "LLM 浮现失败，是 ASI 模型本身就有问题"),
        )
        self.assertEqual(
            patch_fn("今天写作和编程", "今天协作和编程"),
            (5, "协作和编程"),
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


class ReleaseTailTests(unittest.TestCase):
    def test_audio_arriving_after_release_is_decoded_before_finish(self):
        fn = ENGINE["run_utterance"]
        asr = Mock()
        asr.text.return_value = "最后"
        asr.finalize.return_value = "最后一个字"
        bridge = Mock()
        bridge.begin.return_value = True
        bridge.update.return_value = True
        recorder = Mock()
        recorder.poll.return_value = None
        executor = Mock()
        poller = Mock()
        poller.poll.return_value = [(1, 1)]
        clock = [0.0]

        def read_tail(*_args):
            clock[0] += 0.2
            return b"\x01\x00" * 160

        with patch.dict(fn.__globals__, start_request=1, stop_request=1,
                        terminate=False, RELEASE_GRACE_SEC=0.35,
                        start_recorder=lambda _: recorder, resolve_mic=lambda: "",
                        stop_recorder=lambda _: b"", set_state=lambda _: None,
                        set_correction_state=lambda *_: None), \
             patch("select.poll", return_value=poller), \
             patch("os.read", side_effect=read_tail), \
             patch("time.monotonic", side_effect=lambda: clock[0]):
            fn(asr, Mock(), Mock(), bridge, executor, 1)

        self.assertEqual(asr.accept_pcm.call_count, 2)
        asr.finalize.assert_called_once()
        self.assertEqual(executor.submit.call_args.args[2], "最后一个字")
        self.assertEqual(len(executor.submit.call_args.args[3]), 640)


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
            def finish(self, session, text):
                calls.append((session, text))
                return True

        fn = ENGINE["refine_async"]
        with patch.dict(
            fn.__globals__,
            current_session="s1",
            FcitxBridge=AsyncBridge,
        ):
            fn("s1", "实时结果", b"x" * 32000, BrokenFinal(), PunctuationOnly())

        # FireRed failure must not abort the pipeline. The streaming result is
        # retained and committed once with punctuation.
        self.assertEqual(calls, [("s1", "实时结果。")])

    def test_failed_correction_still_gets_sentence_boundary(self):
        calls = []

        class NoFinal:
            def transcribe(self, _pcm):
                return ""

        class FailedCorrector:
            enabled = True
            last_status = "failed"

            def correct(self, text):
                return text

        class AsyncBridge:
            def finish(self, session, text):
                calls.append((session, text))
                return True

        fn = ENGINE["refine_async"]
        with patch.dict(
            fn.__globals__, current_session="s1", FcitxBridge=AsyncBridge
        ):
            fn("s1", "没有标点", b"", NoFinal(), FailedCorrector())

        self.assertEqual(calls, [("s1", "没有标点。")])


class TerminalPunctuationTests(unittest.TestCase):
    def test_adds_only_when_sentence_has_no_ending(self):
        ensure = ENGINE["ensure_terminal_punctuation"]
        self.assertEqual(ensure("这是一句话"), "这是一句话。")
        self.assertEqual(ensure("这是问题？"), "这是问题？")
        self.assertEqual(ensure("你好！”"), "你好！”")
        self.assertEqual(ensure("他说“你好”"), "他说“你好。”")

    def test_stale_session_cancels_late_refinement(self):
        class ShouldNotRun:
            def transcribe(self, _pcm):
                raise AssertionError("stale job should self-cancel")

        fn = ENGINE["refine_async"]
        with patch.dict(fn.__globals__, current_session="new-session"):
            fn("old-session", "旧句", b"x" * 32000, ShouldNotRun(), ShouldNotRun())


if __name__ == "__main__":
    unittest.main()
