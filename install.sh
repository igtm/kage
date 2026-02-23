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

# 強力なクリーンアップ: 以前のバグで混入した壊れた設定を強制的に除去
if [ -f "$CONFIG_PATH" ]; then
    # sed を使って default_ai_engine の行に "${" が含まれている場合はその行を削除し、デフォルトを書きやすくする
    if grep -q "default_ai_engine.*\${" "$CONFIG_PATH"; then
        echo "🧹 壊れた設定を検出しました。修復中..."
        sed -i '/default_ai_engine.*${/d' "$CONFIG_PATH"
    fi
fi

# 現在の設定を取得
CURRENT_VAL=""
if [ -f "$CONFIG_PATH" ]; then
    CURRENT_VAL=$(grep "default_ai_engine" "$CONFIG_PATH" | cut -d'=' -f2 | tr -d ' "' | tr -d "'")
fi

DEFAULT_VAL=${CURRENT_VAL:-"codex"}

echo "AIエンジンを設定します (codex, claude, gemini, copilotなど)。"
# read の前に明示的にエコー
echo -n "使用するAIエンジンを入力してください [現在の設定: $DEFAULT_VAL]: "
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
