# kage 影 - 自律型 AI プロジェクトエージェント

![kage hero](./hero.png)

[English](./README.md) | 日本語

`kage` は、プロジェクト固有の AI エージェントのための自律実行レイヤーです。cron による定期実行、実行間での状態維持（メモリシステム）、および多層的な設定管理を提供します。

## 特徴

- **自律型エージェント・ロジック**: タスクを自動的に Todo リストに分解し、進捗を追跡します。
- **永続メモリ**: `.kage/memory/` にタスクの状態を保存し、次回の実行にコンテキストを引き継ぎます。
- **Markdown 本位**: YAML front matter を持つシンプルな Markdown ファイルでタスクを定義します。
- **多層的なシステムプロンプト**: `system_prompt.md` を使用して、グローバルまたはプロジェクト単位で AI の振る舞いをカスタマイズ。
- **柔軟な設定管理**: 4層の設定: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > デフォルト。
- **Web ダッシュボード**: `http://localhost:8484` で実行履歴とログをリアルタイムに確認。

## インストール

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

または PyPI から:
```bash
pip install kage-ai
```

## クイックスタート

1. **オンボード**: `kage onboard` (グローバルディレクトリとデーモンのセットアップ)
2. **設定**: `~/.kage/config.toml` に `default_ai_engine = "claude"` を設定。
3. **プロジェクト初期化**: リポジトリ内で `kage init` を実行。
4. **タスク定義**: `.kage/tasks/daily_audit.md` を編集。

## タスク定義例 (`.kage/tasks/audit.md`)

```markdown
---
name: プロジェクト監査役
cron: "0 9 * * *"
provider: gemini
---

# タスク: 継続的ヘルスチェック
現在のコードベースを分析し、アーキテクチャの乖離を確認してください。
初回実行時に、メモリ内に Todo リストを作成してください。
次回以降の実行では、リストから項目を1つ選び、詳細なレポートを提供してください。
```

## コマンド

- `kage onboard`: グローバルセットアップ。
- `kage init`: 現在のディレクトリに kage を初期化。
- `kage run`: スケジュールされたすべてのタスクを手動でトリガー。
- `kage ui`: Web ダッシュボードを起動。
- `kage task list`: タスク一覧を表示。
- `kage task run <name>`: 特定のタスクを即座に実行。
- `kage doctor`: 設定と環境の健全性を診断。

## 設定ファイル

- `~/.kage/config.toml`: グローバル設定。
- `.kage/config.toml`: プロジェクト共有設定。
- `.kage/config.local.toml`: ローカル上書き設定 (通常は git-ignore します)。
- `~/.kage/system_prompt.md`: グローバルシステムプロンプト。
- `.kage/system_prompt.md`: プロジェクト固有のシステムプロンプト。
