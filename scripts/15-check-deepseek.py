#!/usr/bin/env python3
"""Fail deployment if the configured DeepSeek correction cannot be called."""
import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
engine = runpy.run_path(str(root / "voiceime-engine"))
corrector = engine["LLMCorrector"]()
if not corrector.enabled or not corrector._available:
    raise SystemExit("DeepSeek enabled in deploy, but API credentials are unavailable")

# Send a harmless fixed phrase; never include the user's recordings in setup.
corrector.correct("请检查 get hub actions 的构建结果")
if corrector.last_status != "success":
    raise SystemExit(f"DeepSeek deployment check failed: {corrector.last_status}")
print(f"DeepSeek API ready: model={corrector.model}, mode={corrector.mode}")
