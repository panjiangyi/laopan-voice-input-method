#!/usr/bin/env python3
"""离线 ASR 验证: 将 wav 文件喂给 Vosk 中文模型，输出识别文本"""
import json
import sys
import wave

import vosk

MODEL_DIR = "/mnt/data/james/Documents/sidework/laopan-voice-input-method/models/vosk-model-small-cn-0.22"


def recognize(wav_path: str) -> str:
    model = vosk.Model(MODEL_DIR)
    rec = vosk.KaldiRecognizer(model, 16000)

    with wave.open(wav_path, "rb") as wf:
        assert wf.getframerate() == 16000, f"采样率 {wf.getframerate()}，需要 16000"
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)

    result = json.loads(rec.FinalResult())
    return result.get("text", "")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 scripts/07-offline-asr.py <wav文件> [期望文本]")
        sys.exit(1)
    wav = sys.argv[1]
    expected = sys.argv[2] if len(sys.argv) > 2 else ""
    text = recognize(wav)
    print(f"识别结果: {text}")
    if expected:
        print(f"期望文本: {expected}")
        print(f"完全匹配: {'是' if text == expected else '否'}")