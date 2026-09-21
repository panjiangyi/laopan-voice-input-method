"""Unit tests for the new engine's text reconciliation logic."""
import runpy
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = runpy.run_path(str(ROOT / "voiceime-engine"))


class FakeBridge:
    def __init__(self):
        self.calls = []

    def update(self, remove, text):
        self.calls.append((remove, text))
        return True


class ReconcilerTests(unittest.TestCase):
    def test_patch_corrects_only_changed_suffix(self):
        patch = ENGINE["TextReconciler"].patch
        self.assertEqual(patch("你好测式", "你好测试"), (1, "试"))
        self.assertEqual(patch("hello wor", "hello world"), (0, "ld"))
        self.assertEqual(patch("今天review", "今天 review"), (6, " review"))

    def test_force_final_correction(self):
        cls = ENGINE["TextReconciler"]
        bridge = FakeBridge()
        r = cls(bridge)
        r.emit("今天review这个PR", force=True)
        r.emit("今天 review 这个 PR", force=True)
        self.assertEqual(bridge.calls[0], (0, "今天review这个PR"))
        self.assertGreater(bridge.calls[1][0], 0)


if __name__ == "__main__":
    unittest.main()
