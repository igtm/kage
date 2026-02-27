# kage 影 - 自律型 AI プロジェクトエージェント

![kage hero](./hero.png)

[English](./README.md) | 日本語

`kage` は、プロジェクト固有の AI エージェントのための自律実行レイヤーです。cron による定期実行、実行間での状態維持（メモリシステム）、および高度なワークフロー制御を提供します。

## 特徴

- **自律型エージェント・ロジック**: タスクを自動的に Todo リストに分解し、進捗を追跡します。
- **永続メモリ**: `.kage/memory/` にタスクの状態を保存し、コンテキストを引き継ぎます。
- **ハイブリッド・タスク**: AI プロンプト（Markdown 本文）と直接コマンド実行（Front Matter 内の `command`）の両方をサポート。
- **高度な制御 (Workflow)**:
    - **実行モード**: `continuous` (常時), `once` (一回), `autostop` (AIが完了判断時に停止)。
    - **多重起動制御**: `allow`, `forbid` (重複スキップ), `replace` (古い方を終了)。
    - **時間枠制限**: `allowed_hours: "9-17"`, `denied_hours: "12"` のように実行時間を制限。
- **Markdown 本位**: YAML front matter を持つシンプルな Markdown ファイルでタスクを定義。
- **多層的な設定**: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > デフォルト。

## インストール

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

## タスク定義例 (`.kage/tasks/audit.md`)

### AI タスク
```markdown
---
name: プロジェクト監査役
cron: "0 * * * *"
provider: gemini
---

# タスク: 継続的ヘルスチェック
現在のコードベースを分析し、アーキテクチャの乖離を確認してください。
```

### シェルコマンド・タスク
```markdown
---
name: ログクリーンアップ
cron: "0 0 * * *"
command: "rm -rf ./logs/*.log"
shell: "bash"
---
毎日深夜に古いログを削除します。
```

## コマンド

- `kage onboard`: グローバルセットアップ。
- `kage init`: 現在のディレクトリに kage を初期化。
- `kage run`: スケジュールされたすべてのタスクを手動でトリガー。
- `kage task list`: タスク一覧を表示。
- `kage task show <name>`: 詳細設定を表示。
- `kage doctor`: 設定と環境の健全性を診断。
- `kage skill`: エージェントの指針（SKILL.md）を表示。

## 設定ファイル

- `~/.kage/config.toml`: グローバル設定。
- `.kage/config.toml`: プロジェクト共有設定。
- `.kage/config.local.toml`: ローカル上書き設定 (git-ignore 推奨)。
- `.kage/system_prompt.md`: プロジェクト固有の AI 指針。
