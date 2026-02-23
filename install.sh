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
echo "📦 kage を GitHub から直接インストール中..."
uv tool install git+https://github.com/igtm/kage.git --reinstall

# 3. 初期化
echo "🚀 セットアップを開始します (kage onboard)..."
kage onboard

# 4. 対話的な設定
echo ""
echo "⚙️  対話的な初期設定を行います。"

# デフォルト設定ファイルのパス
CONFIG_PATH="$HOME/.kage/config.toml"

# 現在の設定を取得（より安全な方法で）
CURRENT_VAL=""
if [ -f "$CONFIG_PATH" ]; then
    # 単純な grep で default_ai_engine の行を探す
    CURRENT_VAL=$(grep "default_ai_engine" "$CONFIG_PATH" | cut -d'=' -f2 | tr -d ' "' | tr -d "'")
fi

# 壊れた文字列が入っている場合は空にする
if [[ "$CURRENT_VAL" == *"\${"* ]]; then
    CURRENT_VAL=""
fi

DEFAULT_VAL=${CURRENT_VAL:-"codex"}

echo "AIエンジンを設定します (codex, claude, gemini, copilotなど)。"
printf "使用するAIエンジンを入力してください [現在の設定: %s]: " "$DEFAULT_VAL"
read INPUT_ENGINE
FINAL_ENGINE=${INPUT_ENGINE:-$DEFAULT_VAL}

if [ -n "$FINAL_ENGINE" ]; then
    # kage config コマンドを使用して確実に書き込む
    kage config default_ai_engine "$FINAL_ENGINE" --global
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
