#!/usr/bin/env bash
# lib.sh - 共享配置与辅助函数（VoiceIME POC）
set -uo pipefail

# ---------- 路径 ----------
POC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NERD_DICTATION_DIR="$POC_ROOT/nerd-dictation"
NERD_DICTATION="$NERD_DICTATION_DIR/nerd-dictation"
MODELS_DIR="$POC_ROOT/models"
LOG_DIR="$POC_ROOT/logs"

# 默认中文模型（小模型，优先低延迟）
DEFAULT_MODEL="vosk-model-small-cn-0.22"
MODEL_DIR="${MODEL_DIR:-$MODELS_DIR/$DEFAULT_MODEL}"

# Vosk 中文模型采样率固定 16000
SAMPLE_RATE="${SAMPLE_RATE:-16000}"

# 输入设备: 固定为已验证可用的 USB 麦克风
# (曾因 PipeWire 默认源切换导致识别出 "gejb"/空结果)
PULSE_DEVICE_NAME="${PULSE_DEVICE_NAME:-alsa_input.usb-Jieli_Technology_USB_Composite_Device_433037383239312E-00.mono-fallback}"

# 输入模式: progressive=边说边输入(默认, 语音输入法体验) | deferred=说完一次性输入
# nerd-dictation 仅 SIMULATE_INPUT 模式支持 progressive; STDOUT 模式强制 deferred
INPUT_MODE="${INPUT_MODE:-progressive}"

# 识别输入工具（X11 默认 xdotool）
SIMULATE_INPUT_TOOL="${SIMULATE_INPUT_TOOL:-XDOTOOL}"

# 优先使用本地编译的 xdotool（免 sudo），其次系统安装
if [ -x "$POC_ROOT/bin/xdotool" ]; then
    export PATH="$POC_ROOT/bin:$PATH"
    export LD_LIBRARY_PATH="$POC_ROOT/bin:${LD_LIBRARY_PATH:-}"
fi

# ---------- 工具检查 ----------
require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[错误] 缺少命令: $cmd" >&2
        return 1
    fi
}

# ---------- 模型检查 ----------
model_ready() {
    if [ ! -d "$MODEL_DIR" ]; then
        echo "[错误] 未找到模型目录: $MODEL_DIR" >&2
        echo "       请先运行: bash scripts/01-setup.sh" >&2
        return 1
    fi
    # Vosk 模型目录至少包含 am 与 conf
    if [ ! -f "$MODEL_DIR/am/final.mdl" ] && [ ! -d "$MODEL_DIR/am" ]; then
        echo "[错误] 模型目录结构不完整: $MODEL_DIR" >&2
        return 1
    fi
}

# ---------- 时间戳 ----------
now_ms() {
    date +%s%3N
}

# ---------- nerd-dictation 前台识别（输出到 stdout，用于验证/延迟测量） ----------
# 用法: nd_recognize_stdout <提示词>
# 过程: 用户说话 -> 回车 -> 测量 end 到进程结束（文字出齐）的耗时
nd_recognize_stdout() {
    local hint="${1:-请说出测试语句}"
    local t0 t1 latency
    local out_file="$LOG_DIR/last_stdout.txt"
    local err_file="$LOG_DIR/last_stderr.txt"

    echo "=============================================="
    echo "  $hint"
    echo "  开始录音后请说话，说完按回车结束。"
    echo "=============================================="

    # 启动后台识别进程（输出到 stdout 文件）
    "$NERD_DICTATION" begin \
        --vosk-model-dir "$MODEL_DIR" \
        --sample-rate "$SAMPLE_RATE" \
        --pulse-device-name "$PULSE_DEVICE_NAME" \
        --output STDOUT \
        --defer-output \
        --verbose 1 \
        >"$out_file" 2>"$err_file" &
    local pid=$!

    # 等待识别进程就绪
    sleep 1

    read -r -p ">>> 说话中... 说完请按回车: " _ignored

    t0="$(now_ms)"
    "$NERD_DICTATION" end >/dev/null 2>&1
    wait "$pid"
    t1="$(now_ms)"
    latency=$((t1 - t0))

    echo ""
    echo "---------- 识别结果 ----------"
    cat "$out_file"
    echo "-------------------------------"
    echo "延迟(end->文字出齐): ${latency} ms"
    echo ""
}

# ---------- 直接输入当前焦点窗口（xdotool） ----------
nd_direct_input() {
    local hint="${1:-请说出测试语句}"
    local t0 t1 latency
    local err_file="$LOG_DIR/last_stderr.txt"

    echo "=============================================="
    echo "  $hint"
    echo "  请先点击目标输入框使其获得焦点！"
    if [ "$INPUT_MODE" = "deferred" ]; then
        echo "  开始录音后请说话，说完按回车一次性输入。"
    else
        echo "  开始录音后请说话，识别结果会实时输入（边说边输入）。"
    fi
    echo "=============================================="

    if [ "$INPUT_MODE" = "deferred" ]; then
        "$NERD_DICTATION" begin \
            --vosk-model-dir "$MODEL_DIR" \
            --sample-rate "$SAMPLE_RATE" \
            --pulse-device-name "$PULSE_DEVICE_NAME" \
            --output SIMULATE_INPUT \
            --simulate-input-tool "$SIMULATE_INPUT_TOOL" \
            --defer-output \
            --verbose 1 \
            >/dev/null 2>"$err_file" &
    else
        "$NERD_DICTATION" begin \
            --vosk-model-dir "$MODEL_DIR" \
            --sample-rate "$SAMPLE_RATE" \
            --pulse-device-name "$PULSE_DEVICE_NAME" \
            --output SIMULATE_INPUT \
            --simulate-input-tool "$SIMULATE_INPUT_TOOL" \
            --verbose 1 \
            >/dev/null 2>"$err_file" &
    fi
    local pid=$!

    sleep 1
    read -r -p ">>> 说话中... 说完请按回车: " _ignored

    t0="$(now_ms)"
    "$NERD_DICTATION" end >/dev/null 2>&1
    wait "$pid"
    t1="$(now_ms)"
    latency=$((t1 - t0))

    echo ""
    echo "文字应已输入到焦点窗口。延迟(end->输入完成): ${latency} ms"
    echo ""
}