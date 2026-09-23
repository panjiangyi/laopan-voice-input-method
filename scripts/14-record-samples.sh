#!/usr/bin/env bash
# Interactive voice sample collector for VoiceIME.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE_RATE="${SAMPLE_RATE:-16000}"
CHANNELS="${CHANNELS:-1}"
LIMIT="${1:-}"
START_INDEX="${2:-${START_INDEX:-1}}"
SAMPLES_ROOT="$ROOT/samples"

latest_session_dir() {
    find "$SAMPLES_ROOT" -maxdepth 1 -type d -name 'voice-input-session-*' -printf '%T@ %p\n' 2>/dev/null \
        | sort -n \
        | tail -1 \
        | cut -d' ' -f2-
}

if [ -z "${SESSION_DIR:-}" ]; then
    if [[ "$START_INDEX" =~ ^[0-9]+$ ]] && [ "$START_INDEX" -gt 1 ]; then
        SESSION_DIR="$(latest_session_dir)"
    fi
    if [ -z "${SESSION_DIR:-}" ]; then
        SESSION_DIR="$SAMPLES_ROOT/voice-input-session-$(date +%Y%m%d-%H%M%S)"
    fi
fi

require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[error] missing command: $cmd" >&2
        exit 1
    fi
}

pause() {
    local prompt="$1"
    if ! read -r -p "$prompt" _ignored; then
        echo ""
        echo "[error] interactive input ended; stopping without starting another sample." >&2
        exit 1
    fi
}

shell_quote() {
    printf "%q" "$1"
}

replace_manifest_row() {
    local id="$1"
    local wav="$2"
    local target_text="$3"
    local actual_text="$4"
    local tmp="$MANIFEST.tmp"

    awk -v sample_id="$id" 'BEGIN { FS = OFS = "\t" } NR == 1 || $1 != sample_id { print }' "$MANIFEST" >"$tmp"
    printf "%s\t%s\t%s\t%s\n" "$id" "$wav" "$target_text" "$actual_text" >>"$tmp"
    mv "$tmp" "$MANIFEST"
}

record_one() {
    local id="$1"
    local text="$2"
    local wav="$SESSION_DIR/$id.wav"
    local log="$SESSION_DIR/$id.ffmpeg.log"
    local actual status

    while true; do
        echo ""
        echo "------------------------------------------------------------"
        echo "$id"
        echo "$text"
        echo "------------------------------------------------------------"
        pause "Press Enter to start recording immediately, then read this line..."
        echo "Recording now. Speak, then press Enter to stop."

        ffmpeg -hide_banner -loglevel warning -nostdin \
            -f pulse -i "$MIC_SOURCE" \
            -ac "$CHANNELS" -ar "$SAMPLE_RATE" \
            -y "$wav" >"$log" 2>&1 &
        local pid=$!

        pause ">>> Recording... press Enter after you finish speaking."
        kill -INT "$pid" >/dev/null 2>&1 || true
        wait "$pid"
        status=$?
        if [ "$status" -ne 0 ] && [ "$status" -ne 255 ]; then
            echo "[warn] ffmpeg exited with status $status. Log: $log"
        fi

        if [ ! -s "$wav" ]; then
            echo "[warn] no audio was written. Retrying this sample."
            continue
        fi

        read -r -p "Transcript correction? Press Enter if exact, type correction, or type r to re-record: " actual
        if [ "$actual" = "r" ] || [ "$actual" = "R" ]; then
            local discarded="$SESSION_DIR/.discarded"
            mkdir -p "$discarded"
            mv "$wav" "$discarded/$id-$(date +%H%M%S).wav" 2>/dev/null || true
            mv "$log" "$discarded/$id-$(date +%H%M%S).ffmpeg.log" 2>/dev/null || true
            continue
        fi
        if [ -z "$actual" ]; then
            actual="$text"
        fi

        replace_manifest_row "$id" "$wav" "$text" "$actual"
        echo "Saved: $wav"
        break
    done
}

PROMPTS=(
    "今天我们先测试一下麦克风，看看中文语音输入能不能稳定识别。"
    "我刚才插上了麦克风，现在想用语音来控制电脑输入文字。"
    "这个项目的目标是让我在日常写作和编程的时候，都可以直接说话输入。"
    "请帮我打开终端，然后切换到 laopan voice input method 这个项目目录。"
    "我希望识别结果不仅中文准确，英文单词、数字、标点和代码变量名也不要乱改。"
    "明天上午十点半，我们一起看一下 pull request 和 GitHub Actions 的结果。"
    "这个 API 的 timeout 先设置成两秒，后面再根据延迟数据调整。"
    "Python 脚本读取 wav 文件，然后调用 sherpa onnx 做离线识别。"
    "如果用户说 user_id 等于 12345，不要把下划线或者数字吞掉。"
    "这个函数叫 updateSession，它负责把临时文本替换成最终文本。"
    "二零二六年九月二十一日，版本号是 v1.3.7，价格是 19.99 美元。"
    "请记录三个数字，分别是负十、一点五和三千零八。"
    "订单编号 A B C 横杠 2026 下划线 test，请不要自动改成普通中文。"
    "我今天写了大约一千二百字，准确率希望能达到百分之九十九。"
    "这个 bug 偶尔出现，大概十次里面会复现两到三次。"
    "嗯，我想一下，这句话先不要提交，等我确认以后再保存。"
    "刚才那段删掉，重新写成：我们需要一个更稳的语音输入流程。"
    "我说话的时候可能会停顿，也可能会自我修正，系统要能处理这种情况。"
    "如果最后识别结果不确定，就保留原文，不要为了通顺强行改写。"
    "现在我要测试一段比较长的句子，里面包含中文、English words、数字 42，以及一点点停顿。"
    "打开 VS Code，搜索 FinalRecognizer，然后看一下异常处理有没有覆盖测试。"
    "把环境变量 VOICEIME_ENABLE_LLM 设置为零，再重新启动 systemd 用户服务。"
    "这条命令是 git commit -m fix voice input safety，不要把横杠删掉。"
    "日志里看到 endpoint triggered，但是最终文本是空字符串。"
    "如果麦克风源切换了，请优先选择 USB 设备，而不是显示器的 monitor source。"
    "今天下午我想连续录三十条样本，然后用独立的十条样本做验收。"
    "这个输入法需要在浏览器、终端、微信和文档编辑器里面都表现稳定。"
    "请把逗号、句号、问号和英文括号都识别出来，不要全部省略。"
    "我喜欢自然一点的输入体验，说完就能看到文字，最好不要等太久。"
    "最后一条样本用于测试收尾，录完以后我们开始跑离线识别评估。"
)

# Optional one-sentence-per-line corpus. Keep the default corpus for existing
# recording sessions; callers can use a dedicated session for a new corpus.
if [ -n "${PROMPTS_FILE:-}" ]; then
    if [ ! -r "$PROMPTS_FILE" ]; then
        echo "[error] cannot read prompts: $PROMPTS_FILE" >&2
        exit 1
    fi
    mapfile -t PROMPTS < <(sed '/^[[:space:]]*$/d; /^[[:space:]]*#/d' "$PROMPTS_FILE")
    if [ "${#PROMPTS[@]}" -eq 0 ]; then
        echo "[error] prompt file is empty" >&2
        exit 1
    fi
fi

require_cmd ffmpeg
require_cmd pactl

if [ -z "$LIMIT" ]; then
    LIMIT="${#PROMPTS[@]}"
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]] || [ "$LIMIT" -lt 1 ]; then
    echo "Usage: $0 [number-of-samples] [start-index]" >&2
    echo "Example: $0 25 6   # record samples S-006 through S-030" >&2
    exit 1
fi
if ! [[ "$START_INDEX" =~ ^[0-9]+$ ]] || [ "$START_INDEX" -lt 1 ]; then
    echo "Usage: $0 [number-of-samples] [start-index]" >&2
    exit 1
fi
if [ "$START_INDEX" -gt "${#PROMPTS[@]}" ]; then
    echo "[error] start-index is past the final prompt: ${#PROMPTS[@]}" >&2
    exit 1
fi

END_INDEX=$((START_INDEX + LIMIT - 1))
if [ "$END_INDEX" -gt "${#PROMPTS[@]}" ]; then
    END_INDEX="${#PROMPTS[@]}"
fi

MIC_SOURCE="${MIC_SOURCE:-$("$ROOT/voiceime-mic")}"
if [ -z "$MIC_SOURCE" ]; then
    echo "[error] no PulseAudio/PipeWire input source found." >&2
    exit 1
fi

mkdir -p "$SESSION_DIR"
MANIFEST="$SESSION_DIR/manifest.tsv"
if [ ! -f "$MANIFEST" ]; then
    printf "id\twav\ttarget_text\tactual_text\n" >"$MANIFEST"
fi

echo "VoiceIME sample recorder"
echo "Mic source: $MIC_SOURCE"
echo "Session: $SESSION_DIR"
echo "Samples: S-$(printf "%03d" "$START_INDEX") through S-$(printf "%03d" "$END_INDEX")"
echo ""
echo "Tip: read naturally. Recording starts immediately when you press Enter on each prompt."
echo "If you make a meaningful mistake, type r after the take to record it again."

i=$((START_INDEX - 1))
while [ "$i" -lt "$END_INDEX" ]; do
    n=$((i + 1))
    id="$(printf "S-%03d" "$n")"
    record_one "$id" "${PROMPTS[$i]}"
    i=$((i + 1))
done

echo ""
echo "Done."
echo "Manifest: $MANIFEST"
echo "Replay one sample:"
echo "  ffplay -nodisp -autoexit $(shell_quote "$SESSION_DIR/$(printf "S-%03d" "$START_INDEX").wav")"
