#!/bin/bash

# kage - One-line Installation Script
# Usage: curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
set -euo pipefail

BOLD='\033[1m'
SUCCESS='\033[38;2;0;229;150m'
INFO='\033[38;2;136;146;176m'
NC='\033[0m'

ui_success() { echo -e "${SUCCESS}✓${NC} $*"; }
ui_info()    { echo -e "${INFO}·${NC} $*"; }
ui_bold()    { echo -e "${BOLD}$*${NC}"; }

get_installed_version() {
    if command -v kage >/dev/null 2>&1; then
        kage --version 2>/dev/null | head -n1 | tr -d '[:space:]'
    else
        echo "not installed"
    fi
}

get_target_version() {
    local target="unknown"
    if command -v curl >/dev/null 2>&1; then
        target="$(curl -fsSL https://pypi.org/pypi/kage-ai/json 2>/dev/null \
            | grep -o '"version":"[^"]*"' \
            | head -n1 \
            | cut -d'"' -f4 || true)"
    fi
    if [[ -z "${target}" ]]; then
        target="unknown"
    fi
    echo "${target}"
}

# 言語判定: $LANG が ja で始まる場合は日本語、それ以外は英語
IS_JA=false
if [[ "${LANG:-}" == ja* ]]; then
    IS_JA=true
fi

# テキスト定義
if $IS_JA; then
    MSG_TITLE="🌑 kage - AI Native Cron Task Runner インストーラー"
    MSG_NO_UV="'uv' が見つかりません。"
    MSG_NO_UV_HINT="  → https://github.com/astral-sh/uv からインストールしてください。"
    MSG_INSTALLING="kage-ai を PyPI からインストール中..."
    MSG_CURR_VER="  現在のバージョン: %s"
    MSG_TARGET_VER="  インストール対象:   %s"
    MSG_AFTER_VER="  インストール後:     %s"
    MSG_INSTALLED="kage のインストール完了"
    MSG_ONBOARD="kage onboard を実行中..."
    MSG_DOCTOR="セットアップ診断を実行中..."
    MSG_DONE="インストール完了！"
    MSG_UI="  Web UI を起動:        kage ui"
    MSG_INIT="  プロジェクト初期化:   kage init"
    MSG_LOGS="  実行ログ表示:         kage logs"
    MSG_AI="  AIエンジンを設定する場合:"
    MSG_AI_CMD="    kage config default_ai_engine codex --global"
    MSG_HACK="Happy hacking! 🌑"
else
    MSG_TITLE="🌑 kage - AI Native Cron Task Runner Installer"
    MSG_NO_UV="'uv' not found."
    MSG_NO_UV_HINT="  → Install it from https://github.com/astral-sh/uv"
    MSG_INSTALLING="Installing kage-ai from PyPI..."
    MSG_CURR_VER="  Current version:     %s"
    MSG_TARGET_VER="  Target version:      %s"
    MSG_AFTER_VER="  Installed version:   %s"
    MSG_INSTALLED="kage installed successfully"
    MSG_ONBOARD="Running kage onboard..."
    MSG_DOCTOR="Running setup diagnostics..."
    MSG_DONE="Installation complete!"
    MSG_UI="  Launch Web UI:         kage ui"
    MSG_INIT="  Initialize a project:  kage init"
    MSG_LOGS="  View execution logs:   kage logs"
    MSG_AI="  To set an AI engine:"
    MSG_AI_CMD="    kage config default_ai_engine codex --global"
    MSG_HACK="Happy hacking! 🌑"
fi

echo ""
ui_bold "$MSG_TITLE"
echo "================================================"
echo ""

# 1. 依存関係チェック
if ! command -v uv &> /dev/null; then
    echo "❌ $MSG_NO_UV"
    echo "$MSG_NO_UV_HINT"
    exit 1
fi

# 2. インストール
CURRENT_VERSION="$(get_installed_version)"
TARGET_VERSION="$(get_target_version)"
ui_info "$MSG_INSTALLING"
ui_info "$(printf "$MSG_CURR_VER" "$CURRENT_VERSION")"
ui_info "$(printf "$MSG_TARGET_VER" "$TARGET_VERSION")"
uv tool install kage-ai --reinstall --force -q
ui_success "$MSG_INSTALLED"
INSTALLED_VERSION="$(get_installed_version)"
ui_success "$(printf "$MSG_AFTER_VER" "$INSTALLED_VERSION")"
echo ""

# 3. 初期化
ui_info "$MSG_ONBOARD"
kage onboard
echo ""

# 4. 診断
ui_info "$MSG_DOCTOR"
kage doctor || true
echo ""

ui_success "$MSG_DONE"
echo ""
echo "$MSG_UI"
echo "$MSG_INIT"
echo "$MSG_LOGS"
echo ""
echo "$MSG_AI"
echo "$MSG_AI_CMD"
echo ""
echo "$MSG_HACK"
