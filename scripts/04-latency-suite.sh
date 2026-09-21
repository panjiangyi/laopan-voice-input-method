#!/usr/bin/env bash
# 04-latency-suite.sh - 跑 PRD 测试用例并记录延迟
# 用法: bash scripts/04-latency-suite.sh [start_index] [end_index]
#   例: bash scripts/04-latency-suite.sh          # 全部用例
#       bash scripts/04-latency-suite.sh 3 5      # 只跑第 3-5 个用例
# 说明: 每个用例会提示你说话，说完按回车，自动测量延迟并让你判断识别质量
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

model_ready || exit 1
require_cmd parec || exit 1

# ---------- 测试用例表（PRD §9） ----------
# 格式: 编号|类别|语句
CASES=(
    "T-001|短句|你好这是一个测试"
    "T-002|短句|今天的天气不错"
    "T-003|短句|我正在使用语音输入"
    "T-004|短句|这个功能可以直接输入"
    "T-005|短句|请帮我记录这个问题"
    "T-101|中长句|我想在 Ubuntu 上实现一个像输入法一样的语音输入工具"
    "T-102|中长句|这个项目第一阶段应该先验证核心链路是否可行"
    "T-103|中长句|如果效果不错后面再考虑基于开源项目进行二次开发"
    "T-201|中英混合|今天 review 一下这个 pull request"
    "T-202|中英混合|我们需要测试 Ubuntu 和 Wayland 的兼容性"
    "T-203|中英混合|这个功能后面可以迁移到 Fcitx5 插件"
)

START_IDX="${1:-1}"
END_IDX="${2:-${#CASES[@]}}"

RESULT_FILE="$LOG_DIR/latency_results_$(date +%Y%m%d_%H%M%S).tsv"
touch "$RESULT_FILE"
echo -e "ID\t类别\t期望语句\t识别结果\t延迟ms\t判定" > "$RESULT_FILE"

echo ">> 延迟测试套件: 共 ${#CASES[@]} 个用例，本次范围 [$START_IDX, $END_IDX]"
echo ">> 结果将记录到: $RESULT_FILE"
echo ">> 每句完成后会问你识别是否正确，请如实打分。"
echo ""

for (( i=START_IDX; i<=END_IDX; i++ )); do
    idx=$((i-1))
    IFS='|' read -r id category phrase <<< "${CASES[$idx]}"
    echo ""
    echo "########## [$i/${#CASES[@]}] $id ($category) ##########"
    echo ">>> 请说出: \"$phrase\""
    echo ""

    # 捕获识别结果 + 延迟
    out_file="$LOG_DIR/case_$id.txt"
    err_file="$LOG_DIR/case_${id}_stderr.txt"
    t0=""
    latency=""

    "$NERD_DICTATION" begin \
        --vosk-model-dir "$MODEL_DIR" \
        --sample-rate "$SAMPLE_RATE" \
        --pulse-device-name "$PULSE_DEVICE_NAME" \
        --output STDOUT \
        --defer-output \
        --verbose 1 \
        >"$out_file" 2>"$err_file" &
    pid=$!

    sleep 1
    read -r -p ">>> 说话中... 说完请按回车: " _ignored
    t0="$(now_ms)"
    "$NERD_DICTATION" end >/dev/null 2>&1
    wait "$pid"
    latency=$(( $(now_ms) - t0 ))

    result_text="$(cat "$out_file" | tr '\n' ' ')"
    echo "  识别结果: $result_text"
    echo "  延迟: ${latency} ms"

    # 判定
    read -r -p "  识别是否正确？(y=正确 n=错误 s=跳过) [y/n/s]: " verdict
    case "$verdict" in
        y|Y) judgment="PASS" ;;
        n|N) judgment="FAIL" ;;
        *)   judgment="SKIP" ;;
    esac
    echo -e "$id\t$category\t$phrase\t$result_text\t$latency\t$judgment" >> "$RESULT_FILE"
done

echo ""
echo "========== 测试完成 =========="
echo "结果文件: $RESULT_FILE"
echo ""
# 汇总
echo "汇总统计:"
awk -F'\t' 'NR>1 {n++; if($6=="PASS") p++; if($6=="FAIL") f++; sum+=$5} END {
    printf "  总用例: %d  PASS: %d  FAIL: %d  SKIP: %d\n", n, p, f, n-p-f
    if(n>0 && sum>0) printf "  平均延迟: %.0f ms\n", sum/n
}' "$RESULT_FILE"