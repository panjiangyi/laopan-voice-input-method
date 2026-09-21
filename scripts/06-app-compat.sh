#!/usr/bin/env bash
# 06-app-compat.sh - 应用兼容性测试 (A-001..A-005)
# 用法: bash scripts/06-app-compat.sh
# 说明: 逐个启动目标应用，提示你聚焦输入框并说话，记录直接输入是否成功。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

model_ready || exit 1

RESULT_FILE="$LOG_DIR/app_compat_$(date +%Y%m%d_%H%M%S).tsv"
touch "$RESULT_FILE"
echo -e "编号\t应用\t命令\t结果\t备注" > "$RESULT_FILE"

# 编号|应用名|启动命令
APPS=(
    "A-001|Firefox|firefox"
    "A-002|Chrome|google-chrome"
    "A-003|Text Editor|gnome-text-editor"
    "A-004|VS Code|code"
    "A-005|LibreOffice Writer|libreoffice"
)

for entry in "${APPS[@]}"; do
    IFS='|' read -r id app_name cmd <<< "$entry"
    echo ""
    echo "########## $id $app_name ##########"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "  未安装，跳过。"
        echo -e "$id\t$app_name\t$cmd\tSKIP\t未安装" >> "$RESULT_FILE"
        continue
    fi
    echo "  启动 $app_name 并聚焦输入框..."
    nohup "$cmd" >/dev/null 2>&1 &
    sleep 3
    echo "  在 $app_name 中输入框点击获得焦点，然后进行测试。"
    read -r -p "  准备好了吗？按回车开始录音: " _ignored
    nd_direct_input "应用兼容性测试 $id"
    read -r -p "  文字是否正确输入？(y=成功 n=失败 s=跳过) [y/n/s]: " verdict
    case "$verdict" in
        y|Y) judgment="PASS" ;;
        n|N) judgment="FAIL" ;;
        *)   judgment="SKIP" ;;
    esac
    read -r -p "  备注(如: 乱码/丢字/焦点丢失/正常): " note
    echo -e "$id\t$app_name\t$cmd\t$judgment\t$note" >> "$RESULT_FILE"
done

echo ""
echo "========== 应用兼容性测试完成 =========="
echo "结果文件: $RESULT_FILE"
cat "$RESULT_FILE"