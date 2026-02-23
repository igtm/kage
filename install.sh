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

# 強力なクリーンアップ
if [ -f "$CONFIG_PATH" ]; then
    if grep -q "default_ai_engine" "$CONFIG_PATH"; then
        echo "🧹 既存の設定をクリーンアップ中..."
        # 以前の壊れた設定や既存の設定を一旦削除して、確実に新しく書く
        sed -i '/default_ai_engine/d' "$CONFIG_PATH"
    fi
else
    mkdir -p "$(dirname "$CONFIG_PATH")"
    touch "$CONFIG_PATH"
fi

# 現在の設定を取得（削除済みなのでデフォルトを表示）
DEFAULT_VAL="codex"

echo "AIエンジンを設定します (codex, claude, gemini, copilotなど)。"
echo -n "使用するAIエンジンを入力してください [デフォルト: $DEFAULT_VAL]: "
read INPUT_ENGINE
FINAL_ENGINE=${INPUT_ENGINE:-$DEFAULT_VAL}

if [ -n "$FINAL_ENGINE" ]; then
    # 直接ファイルに書き込む（CLIコマンドに頼らない確実な方法）
    echo "default_ai_engine = \"$FINAL_ENGINE\"" >> "$CONFIG_PATH"
    echo "✅ default_ai_engine = \"$FINAL_ENGINE\" を $CONFIG_PATH に保存しました。"
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
