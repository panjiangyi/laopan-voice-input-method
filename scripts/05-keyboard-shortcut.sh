#!/usr/bin/env bash
# 05-keyboard-shortcut.sh - 配置 GNOME 自定义快捷键 (P1)
# 用法: bash scripts/05-keyboard-shortcut.sh
# 说明: 为「开始听写 / 结束听写」绑定系统快捷键。
#       默认 Ctrl+Alt+V 开始，Ctrl+Alt+B 结束。
#       需要 sudo 权限以写入系统 dconf (或允许用户在图形界面手动配置)。
# 注意: 快捷键脚本依赖 xdotool 获取当前窗口，真正的工作目录必须固定。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 稳定的 begin/end 包装脚本（含 DISPLAY/PATH/LD_LIBRARY_PATH 环境）
VOICEIME_BIN="$POC_ROOT/voiceime-begin"
VOICEIME_END="$POC_ROOT/voiceime-end"
for f in "$VOICEIME_BIN" "$VOICEIME_END"; do
    [ -x "$f" ] || { echo "[错误] 缺少 $f"; exit 1; }
done

# 通过 gsettings 配置自定义快捷键（无需 sudo，写入用户 dconf）
custom_path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voiceime-begin/"
custom_path_end="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voiceime-end/"

existing="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)"
echo "当前自定义快捷键: $existing"

new_list="${existing%]*}, '$custom_path', '$custom_path_end']"
if [ "$existing" = "@as []" ] || [ -z "$existing" ]; then
    new_list="['$custom_path', '$custom_path_end']"
fi
gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$new_list"

gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$custom_path" name 'VoiceIME Begin'
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$custom_path" command "$VOICEIME_BIN"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$custom_path" binding '<Control><Alt>v'

gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$custom_path_end" name 'VoiceIME End'
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$custom_path_end" command "$VOICEIME_END"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$custom_path_end" binding '<Control><Alt>b'

echo ""
echo "快捷键已配置:"
echo "  Ctrl+Alt+V  -> 开始听写 ($VOICEIME_BIN)"
echo "  Ctrl+Alt+B  -> 结束听写 ($VOICEIME_END)"
echo ""
echo "验证: gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings"
echo "说明: 若快捷键不生效，请在 设置 -> 键盘 -> 查看自定义快捷键 中检查。"
echo "注意: begin 使用 xdotool 需要焦点窗口，Wayland 下需改用 ydotool。"