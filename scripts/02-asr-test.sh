#!/usr/bin/env bash
# 02-asr-test.sh - 验证录音 + 中文识别（结果输出到屏幕，不注入窗口）
# 用法: bash scripts/02-asr-test.sh ["可选的测试短语"]
# 说明: 运行后说话，说完按回车，识别文字会显示在屏幕（不进入任何窗口）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

model_ready || exit 1
require_cmd parec || exit 1

HINT="${1:-你好，这是一个语音输入测试}"

echo ">> 验证模式: 录音 -> 中文识别 -> 结果输出到屏幕（不注入窗口）"
echo ">> 请对准麦克风说出: \"$HINT\""
echo ""

nd_recognize_stdout "$HINT"