#!/bin/bash

# kage - One-line Installation Script
# Usage: curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
set -euo pipefail

# # # # # # # # # # # # # # # # # # # # # #
# ユーティリティ
# # # # # # # # # # # # # # # # # # # # # #

BOLD='\033[1m'
SUCCESS='\033[38;2;0;229;150m'
WARN='\033[38;2;255;176;32m'
ERROR='\033[38;2;230;57;70m'
INFO='\033[38;2;136;146;176m'
NC='\033[0m'

ui_success() { echo -e "${SUCCESS}✓${NC} $*"; }
ui_warn()    { echo -e "${WARN}!${NC} $*"; }
ui_error()   { echo -e "${ERROR}✗${NC} $*" >&2; }
ui_info()    { echo -e "${INFO}·${NC} $*"; }
ui_bold()    { echo -e "${BOLD}$*${NC}"; }

# curl | bash では stdin がパイプになるため、
# tty (端末) かどうかで対話モードを判定する
is_interactive() {
    [[ -t 0 && -t 1 ]]
}

# # # # # # # # # # # # # # # # # # # # # #
# メイン処理
# # # # # # # # # # # # # # # # # # # # # #

echo ""
ui_bold "🌑 kage - AI Native Cron Task Runner Installer"
echo "================================================"
echo ""

# 1. 依存関係チェック
if ! command -v uv &> /dev/null; then
    ui_error "'uv' が見つかりません。"
    echo "  → https://github.com/astral-sh/uv からインストールしてください。"
    exit 1
fi

# 2. インストール
ui_info "kage を GitHub から直接インストール中..."
uv tool install git+https://github.com/igtm/kage.git --reinstall -q
ui_success "kage のインストール完了"
echo ""

# 3. 初期化
ui_info "kage onboard を実行中..."
kage onboard
echo ""

# 4. 対話的な設定（端末で実行している場合のみ）
if is_interactive; then
    ui_bold "⚙️  対話的な初期設定"
    echo "AIエンジンを設定します (codex, claude, gemini, copilot など)。"
    echo "使用しない場合は Enter を押してスキップできます。"
    echo ""

    CONFIG_PATH="$HOME/.kage/config.toml"
    
    # 現在の設定を取得
    CURRENT_VAL=""
    if [ -f "$CONFIG_PATH" ]; then
        RAW_VAL=$(grep "default_ai_engine" "$CONFIG_PATH" | cut -d'=' -f2 | tr -d ' "' | tr -d "'" 2>/dev/null || true)
        # 壊れた文字列（${...}を含む）は除外
        if [[ "$RAW_VAL" != *'${'* ]] && [[ -n "$RAW_VAL" ]]; then
            CURRENT_VAL="$RAW_VAL"
            # 壊れた行は先に削除しておく
        fi
    fi

    PROMPT_HINT="${CURRENT_VAL:-codex}"
    read -rp "default_ai_engine [${PROMPT_HINT}]: " INPUT_ENGINE
    FINAL_ENGINE=${INPUT_ENGINE:-$PROMPT_HINT}

    if [ -n "$FINAL_ENGINE" ]; then
        # 古い行を削除してから書き込む（sed -i）
        if [ -f "$CONFIG_PATH" ]; then
            sed -i '/default_ai_engine/d' "$CONFIG_PATH"
        else
            mkdir -p "$(dirname "$CONFIG_PATH")"
        fi
        echo "default_ai_engine = \"$FINAL_ENGINE\"" >> "$CONFIG_PATH"
        ui_success "default_ai_engine = \"$FINAL_ENGINE\" を設定しました"
    fi
    echo ""
else
    ui_warn "非対話モード（curl | bash）で実行中のため、AI エンジンの設定をスキップします。"
    echo "  → インストール後に以下のコマンドで設定できます:"
    echo "     kage config default_ai_engine codex --global"
    echo ""
fi

# 5. 診断
ui_info "セットアップ診断を実行中..."
kage doctor || true
echo ""

ui_success "インストール完了！"
echo ""
echo "  Web UI を起動:       kage ui"
echo "  プロジェクト初期化:  kage init"
echo "  実行ログ表示:        kage logs"
echo "  AI エンジン設定:     kage config default_ai_engine <engine> --global"
echo ""
echo "Happy hacking! 🌑"
