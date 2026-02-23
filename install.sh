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

echo ""
ui_bold "🌑 kage - AI Native Cron Task Runner Installer"
echo "================================================"
echo ""

# 1. 依存関係チェック
if ! command -v uv &> /dev/null; then
    echo "❌ 'uv' が見つかりません。"
    echo "  → https://github.com/astral-sh/uv からインストールしてください。"
    exit 1
fi

# 2. インストール
ui_info "kage を GitHub からインストール中..."
uv tool install git+https://github.com/igtm/kage.git --reinstall -q
ui_success "kage のインストール完了"
echo ""

# 3. 初期化
ui_info "kage onboard を実行中..."
kage onboard
echo ""

# 4. 診断
ui_info "セットアップ診断を実行中..."
kage doctor || true
echo ""

ui_success "インストール完了！"
echo ""
echo "  Web UI を起動:       kage ui"
echo "  プロジェクト初期化:  kage init"
echo "  実行ログ表示:        kage logs"
echo ""
echo "  AIエンジンを設定する場合:"
echo "    kage config default_ai_engine codex --global"
echo ""
echo "Happy hacking! 🌑"
