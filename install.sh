#!/bin/bash

# kage - One-line Installation Script
set -e

echo "🌑 kage - AI Native Cron Task Runner Installation"
echo "================================================"

# 1. 依存関係チェック
if ! command -v uv &> /dev/null; then
    echo "❌ 'uv' が見つかりません。https://github.com/astral-sh/uv からインストールしてください。"
    exit 1
fi

# 2. ツールとしてのインストール
# リポジトリをクローンせずに実行する場合、GitHubのURLから直接インストール
echo "📦 kage を GitHub から直接インストール中..."
uv tool install git+https://github.com/igtm/kage.git --reinstall

# 3. 初期化
echo "🚀 セットアップを開始します (kage onboard)..."
kage onboard

# 4. 対話的な設定
echo ""
echo "⚙️  対話的な初期設定を行います。"

# Default AI Engine の現在の設定を確認
# doctor がエラーでも設定だけは抜く（未設定なら空）
DEFAULT_ENGINE=$(kage config default_ai_engine --global 2>/dev/null | grep -oP '= \K.*' || echo "codex")

echo "AIエンジンを設定します (codex, claude, gemini, copilotなど)。"
read -p "使用するAIエンジンを入力してください [現在の設定: $DEFAULT_ENGINE]: " NEW_ENGINE
NEW_ENGINE=${NEW_ENGINE:-$DEFAULT_ENGINE}

if [ -n "$NEW_ENGINE" ]; then
    kage config default_ai_engine "$NEW_ENGINE" --global
fi

# 5. 診断実行
echo ""
echo "🩺 セットアップ診断 (kage doctor) を実行します..."
kage doctor

echo ""
echo "✅ インストールが完了しました！"
echo "  - Web UI を起動する場合: kage ui"
echo "  - プロジェクトを新しく始める場合: kage init"
echo "  - 実行履歴を表示する場合: kage logs"
echo ""
echo "Happy hacking! 🌑"
