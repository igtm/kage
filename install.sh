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
ui_info "$MSG_INSTALLING"
uv tool install kage-ai --reinstall --force -q
ui_success "$MSG_INSTALLED"
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
