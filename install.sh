#!/bin/bash

# kage - One-line Installation Script
set -e

echo "🌑 kage - AI Native Cron Task Runner Installation"
echo "================================================"

# 1. 依存関係チェック
if ! command -v uv &> /dev/null; then
    echo "❌ 'uv' が見つかりません。https://github.com/astral-sh/uv からインストールしてください。"
    echo "   → https://github.com/astral-sh/uv"
    exit 1
fi

# 2. ツールとしてのインストール
echo "📦 kage を GitHub から直接インストール中..."
uv tool install git+https://github.com/igtm/kage.git --reinstall

# 3. 初期化
echo "🚀 セットアップを開始します (kage onboard)..."
kage onboard

# 4. 診断実行
echo ""
echo "🩺 セットアップ診断 (kage doctor) を実行します..."
kage doctor || true

echo ""
echo "✅ インストールが完了しました！"
echo ""
echo "📝 次のステップ: AIエンジンを設定してください:"
echo "   kage config default_ai_engine codex --global"
echo "   kage config default_ai_engine claude --global"
echo "   kage config default_ai_engine gemini --global"
echo ""
echo "  - Web UI を起動する場合: kage ui"
echo "  - プロジェクトを新しく始める場合: kage init"
echo "  - 実行履歴を表示する場合: kage logs"
echo ""
echo "Happy hacking! 🌑"
