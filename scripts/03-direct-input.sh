#!/usr/bin/env bash
# 03-direct-input.sh - 验证「直接输入当前焦点窗口」（核心验证点）
# 用法: bash scripts/03-direct-input.sh ["可选的测试短语"]
# 说明: 
#   1. 先打开一个文本编辑器/浏览器输入框，点击使其获得焦点
#   2. 运行本脚本，说话，按回车
#   3. 识别文字应直接出现在焦点窗口，无需复制粘贴
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

model_ready || exit 1
require_cmd "$( [ "$SIMULATE_INPUT_TOOL" = XDOTOOL ] && echo xdotool || echo ydotool )" || exit 1

HINT="${1:-你好，这是一个直接输入测试}"

echo ">> 验证模式: 录音 -> 中文识别 -> xdotool 注入当前焦点窗口"
echo ">> 请先打开目标应用（编辑器/浏览器/聊天框），点击输入框获得焦点"
echo ">> 然后说出: \"$HINT\""
echo ""

nd_direct_input "$HINT"

echo ">> 请确认上面这句话是否出现在你刚才聚焦的输入框中:"
echo "   [y] 是，文字正确进入输入框"
echo "   [n] 否，文字没有进入 / 进入错误"
read -r -p "确认结果 (y/n): " verdict
case "$verdict" in
    y|Y) echo "RESULT=PASS 直接输入验证通过" | tee -a "$LOG_DIR/direct_input_results.txt" ;;
    *)   echo "RESULT=FAIL 直接输入验证失败（详见 stderr: $LOG_DIR/last_stderr.txt）" | tee -a "$LOG_DIR/direct_input_results.txt" ;;
esac