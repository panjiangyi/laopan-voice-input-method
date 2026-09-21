#!/usr/bin/env bash
# 00-user-test.sh - 真人语音测试一键入口
# 用法: bash scripts/00-user-test.sh
# 说明: 依次运行 02(识别) → 03(直接输入) → 04(延迟套件), 全程只需你说话+按回车
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "======================================================"
echo " VoiceIME POC - 真人语音测试"
echo "======================================================"
echo "测试前请确认:"
echo "  1. 麦克风已连接且系统音量正常"
echo "  2. 保持环境安静"
echo "  3. 每步按提示说话, 说完按回车"
echo ""
echo "将依次运行:"
echo "  [1/3] 语音识别测试 (结果输出到屏幕, 不注入窗口)"
echo "  [2/3] 直接输入测试 (先点击目标输入框, 文字直接进入)"
echo "  [3/3] 11 个延迟测试用例 (T-001..T-203)"
echo ""
read -r -p "准备好了吗? 按回车开始 [1/3] 语音识别测试: " _ignored

echo ""
echo "########## [1/3] 语音识别测试 ##########"
echo ">> 屏幕会显示识别结果。请对准麦克风说: 你好，这是一个语音输入测试"
echo ">> 接下来会出现 '说话中...' 提示，那时开始说话，说完按回车结束。"
sleep 2
bash "$SCRIPT_DIR/02-asr-test.sh" "你好，这是一个语音输入测试"

echo ""
read -r -p "识别结果可读吗? 按回车继续 [2/3] 直接输入测试: " _ignored

echo ""
echo "########## [2/3] 直接输入测试 ##########"
echo ">> 请先打开一个文本编辑器(如 gnome-text-editor), 点击输入框获得焦点"
read -r -p "聚焦好后按回车开始: " _ignored
bash "$SCRIPT_DIR/03-direct-input.sh" "你好，这是一个直接输入测试"

echo ""
read -r -p "文字是否进入了输入框? 按回车继续 [3/3] 延迟测试套件: " _ignored

echo ""
echo "########## [3/3] 延迟测试套件 (11 用例) ##########"
echo ">> 每句会提示你说话, 说完按回车, 自动测延迟并问你是否正确"
read -r -p "开始前请确认麦克风就绪, 按回车启动: " _ignored
bash "$SCRIPT_DIR/04-latency-suite.sh"

echo ""
echo "======================================================"
echo " 全部完成! 结果已记录到:"
echo "  $POC_ROOT/logs/latency_results_*.tsv"
echo "  $POC_ROOT/logs/direct_input_results.txt"
echo "======================================================"