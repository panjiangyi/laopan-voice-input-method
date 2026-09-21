#!/usr/bin/env bash
# 01-setup.sh - VoiceIME POC 环境准备（一次性）
# 用法: bash scripts/01-setup.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

echo "========== VoiceIME POC - 环境准备 =========="
echo "POC 目录: $POC_ROOT"
echo ""

# ---------- 1. 系统依赖 ----------
echo "[1/5] 安装系统依赖 (xdotool unzip 等, 需要 sudo)..."
APT_PKGS=(xdotool unzip curl pulseaudio-utils)
sudo apt-get update
sudo apt-get install -y "${APT_PKGS[@]}"

for cmd in xdotool unzip curl parec; do
    require_cmd "$cmd" || { echo "[错误] 依赖安装失败: $cmd"; exit 1; }
done
echo "  -> 系统依赖 OK"
echo ""

# ---------- 2. Python 依赖 ----------
echo "[2/5] 安装 Python 依赖 (vosk)..."
if ! python3 -c "import vosk" 2>/dev/null; then
    pip3 install --user --break-system-packages vosk 2>&1 | tail -3 || pip3 install --user vosk 2>&1 | tail -3
fi
python3 -c "import vosk; print('  -> vosk 版本:', vosk.__version__ if hasattr(vosk,'__version__') else 'installed')" || { echo "[错误] vosk 安装失败"; exit 1; }
echo ""

# ---------- 3. 下载 Vosk 中文模型 ----------
echo "[3/5] 下载 Vosk 中文模型..."
if [ ! -d "$MODEL_DIR" ]; then
    mkdir -p "$MODELS_DIR"
    local_zip="$MODELS_DIR/$DEFAULT_MODEL.zip"
    echo "  下载 $DEFAULT_MODEL (~42MB)..."
    curl -L -o "$local_zip" "https://alphacephei.com/vosk/models/$DEFAULT_MODEL.zip"
    echo "  解压中..."
    unzip -q -o "$local_zip" -d "$MODELS_DIR"
    rm -f "$local_zip"
fi
model_ready && echo "  -> 模型 OK: $MODEL_DIR"
echo ""

# ---------- 4. 检查录音设备 ----------
echo "[4/5] 检查音频设备..."
if command -v pactl >/dev/null 2>&1; then
    echo "  当前默认录音源:"
    pactl get-default-source 2>/dev/null || echo "    (无法获取默认源)"
    echo "  可用录音源:"
    pactl list sources short 2>/dev/null | grep -i input | head -5 || echo "    (无输入源?)"
fi
echo ""

# ---------- 5. 验证 nerd-dictation ----------
echo "[5/5] 验证 nerd-dictation..."
if [ -x "$NERD_DICTATION" ]; then
    echo "  nerd-dictation 可执行: $NERD_DICTATION"
else
    echo "  [错误] nerd-dictation 不存在，请确认已 clone 到 $NERD_DICTATION_DIR"
    exit 1
fi

echo ""
echo "========== 环境准备完成 =========="
echo "下一步:"
echo "  bash scripts/02-asr-test.sh        # 验证录音+中文识别（输出到屏幕）"
echo "  bash scripts/03-direct-input.sh    # 验证直接输入当前窗口"
echo "  bash scripts/04-latency-suite.sh   # 跑测试用例并记录延迟"
echo "  bash scripts/05-keyboard-shortcut.sh # 配置 GNOME 快捷键 (P1)"