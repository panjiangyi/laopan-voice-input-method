#!/usr/bin/env python3
"""批量离线 ASR 验证: 跑 PRD 全部 T-001..T-203 用例, 输出对比表"""
import json
import sys
import wave

import vosk

MODEL_DIR = "/mnt/data/james/Documents/sidework/laopan-voice-input-method/models/vosk-model-small-cn-0.22"
LOG_DIR = "/mnt/data/james/Documents/sidework/laopan-voice-input-method/logs"

CASES = [
    ("T-001", "你好这是一个测试"),
    ("T-002", "今天的天气不错"),
    ("T-003", "我正在使用语音输入"),
    ("T-004", "这个功能可以直接输入"),
    ("T-005", "请帮我记录这个问题"),
    ("T-101", "我想在Ubuntu上实现一个像输入法一样的语音输入工具"),
    ("T-102", "这个项目第一阶段应该先验证核心链路是否可行"),
    ("T-103", "如果效果不错后面再考虑基于开源项目进行二次开发"),
    ("T-201", "今天review一下这个pull request"),
    ("T-202", "我们需要测试Ubuntu和Wayland的兼容性"),
    ("T-203", "这个功能后面可以迁移到Fcitx5插件"),
]


def recognize(model, wav_path: str) -> str:
    rec = vosk.KaldiRecognizer(model, 16000)
    with wave.open(wav_path, "rb") as wf:
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
    return json.loads(rec.FinalResult()).get("text", "")


def main():
    model = vosk.Model(MODEL_DIR)
    rows = []
    for cid, expected in CASES:
        wav = f"{LOG_DIR}/{cid}_16k.wav"
        text = recognize(model, wav)
        exp_norm = expected.replace(" ", "").lower()
        got_norm = text.replace(" ", "").lower()
        exact = exp_norm == got_norm
        # 简单包含判断: 期望中的每个汉字是否出现在结果中
        overlap = sum(1 for ch in set(exp_norm) if ch in got_norm) / max(len(set(exp_norm)), 1)
        rows.append((cid, expected, text, exact, overlap))
        print(f"{cid}: 期望={expected}")
        print(f"      识别={text}")
        print(f"      精确={exact} 字符重合率={overlap:.0%}")
        print()

    n_exact = sum(1 for r in rows if r[3])
    n_total = len(rows)
    avg_overlap = sum(r[4] for r in rows) / n_total
    print(f"=== 汇总: 精确匹配 {n_exact}/{n_total}, 平均字符重合率 {avg_overlap:.0%} ===")


if __name__ == "__main__":
    main()