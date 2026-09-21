"""Regression tests without recording the microphone or typing on the desktop."""
import io
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PTT = runpy.run_path(str(ROOT / "voiceime-ptt"))
ND = runpy.run_path(str(ROOT / "nerd-dictation/nerd-dictation"))


class KeyTests(unittest.TestCase):
    def test_synthetic_release_cannot_stop_physical_hold(self):
        parser = PTT["KeyEvents"]({5})
        events = []
        for source, event in [(22, "RawKeyPress"), (5, "RawKeyRelease"),
                              (5, "RawKeyPress"), (22, "RawKeyRelease")]:
            for line in ["EVENT type 13 (%s)" % event,
                         "    device: 3 (%d)" % source, "    detail: 108"]:
                result = parser.feed(line)
                if result:
                    events.append(result)
        self.assertEqual(events, [("RawKeyPress", 108), ("RawKeyRelease", 108)])

    def test_unknown_source_is_not_a_physical_key(self):
        parser = PTT["KeyEvents"]({5})
        parser.feed("EVENT type 13 (RawKeyPress)")
        self.assertIsNone(parser.feed("    detail: 108"))

    def test_backspace_and_text_clear_modifiers(self):
        fn = ND["simulate_typing_with_xdotool"]
        with patch.dict(fn.__globals__, run_command_or_exit_on_failure=lambda cmd: commands.append(cmd)):
            commands = []
            fn(3, "天气")
        self.assertEqual(len(commands), 2)
        self.assertTrue(all("--clearmodifiers" in cmd for cmd in commands))


class StreamingTests(unittest.TestCase):
    def test_fragments_are_aligned_and_output_is_progressive(self):
        chunks = []
        output = []

        class Recorder:
            def __init__(self):
                self.returncode = None

            def poll(self):
                return self.returncode

            def send_signal(self, sig):
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode

        class Recognizer:
            def AcceptWaveform(self, data):
                chunks.append(data)
                return False

            def PartialResult(self):
                return '{"partial":"你好"}'

            def FinalResult(self):
                return '{"text":"你好"}'

        class Pipe:
            def __init__(self):
                self.parts = iter([b'a', None, b'b' * 3199, b'cc'])

            def read(self, size):
                return next(self.parts, None)

            def close(self):
                pass

        class Vosk:
            SetLogLevel = staticmethod(lambda level: None)
            Model = staticmethod(lambda path: None)
            KaldiRecognizer = staticmethod(lambda *args: Recognizer())

        calls = 0

        def exit_fn(handled):
            nonlocal calls
            calls += 1
            if calls == 5:
                self.assertIn((0, "你好"), output, "must type before recording ends")
                return 1
            return 0

        fn = ND["text_from_vosk_pipe"]
        with patch.dict(sys.modules, vosk=Vosk), patch("signal.signal"), patch.dict(
            fn.__globals__, recording_proc_with_non_blocking_stdout=lambda *args: (Recorder(), Pipe())
        ):
            fn(vosk_model_dir=str(ROOT), exit_fn=exit_fn, process_fn=lambda s: s,
               handle_fn=lambda n, s: output.append((n, s)), timeout=0, idle_time=0,
               progressive=True, progressive_continuous=False, sample_rate=16000,
               input_method="PAREC")
        self.assertEqual(b"".join(chunks), b'a' + b'b' * 3199 + b'cc')
        self.assertTrue(all(len(data) % 2 == 0 for data in chunks))
        self.assertEqual(len(chunks[0]), 3200)

    def test_suspend_during_output_does_not_reenter_output(self):
        # A real signal delivered while a writer is busy used to call that
        # writer recursively from the suspend handler.
        script = r'''
import os, runpy, signal, subprocess, sys, types
nd = runpy.run_path(sys.argv[1])
class Rec:
    def AcceptWaveform(self, data): return False
    def PartialResult(self): return '{"partial":"hello"}'
    def FinalResult(self): return '{"text":"hello world"}'
    def Reset(self): pass
sys.modules['vosk'] = types.SimpleNamespace(SetLogLevel=lambda n: None,
    Model=lambda p: None, KaldiRecognizer=lambda *args: Rec())
def recorder(*args):
    p = subprocess.Popen([sys.executable, '-c',
        "import os,time; os.write(1,b'x'*3200); time.sleep(30)"], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL)
    os.set_blocking(p.stdout.fileno(), False)
    return p, p.stdout
busy = False
sent = False
def output(n, s):
    global busy, sent
    if n < 0: return
    assert not busy, 'reentrant text output'
    busy = True
    if not sent:
        sent = True
        os.kill(os.getpid(), signal.SIGUSR1)
    busy = False
fn = nd['text_from_vosk_pipe']
fn.__globals__['recording_proc_with_non_blocking_stdout'] = recorder
fn(vosk_model_dir=sys.argv[2], exit_fn=lambda handled: 0, process_fn=lambda s:s,
    handle_fn=output, timeout=0, idle_time=.01, progressive=True,
    progressive_continuous=False, sample_rate=16000, input_method='PAREC')
'''
        with tempfile.TemporaryFile() as errors:
            p = subprocess.Popen([sys.executable, "-c", script,
                                  str(ROOT / "nerd-dictation/nerd-dictation"), str(ROOT)],
                                 stderr=errors, start_new_session=True)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if p.poll() is not None or PTT["proc_state"](p.pid) == "T":
                        break
                    time.sleep(.02)
                errors.seek(0)
                self.assertIsNone(p.poll(), errors.read().decode())
                self.assertEqual(PTT["proc_state"](p.pid), "T")
            finally:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()


if __name__ == "__main__":
    unittest.main()
