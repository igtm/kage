# kage 影 - AI Native Cron Task Runner

![kage hero](./hero.png)

[English](./README.md) | 日本語

`kage` は、プロジェクトごとのタスクを AI CLI（codex, claude, gemini等）や標準のシェルコマンドを使って定期的に実行するためのツールです。

## 特徴

- **AIネイティブ**: プロンプトを直接 `cron` スケジュールで実行可能。
- **柔軟なAIプロバイダー**: `codex`, `claude`, `gemini`, `copilot` などを標準サポートし、カスタマイズも容易。
- **インライン設定**: 個別のタスクごとに実行コマンドやAIモデル、パーサー（jq等）を自由に上書き可能。
- **3層の設定マージ**: システムデフォルト、ユーザー（~/.kage）、ワークスペース（.kage）の順に設定を重ね合わせ。
- **Web UI**: タスクの実行状態やログをブラウザで確認可能。

## インストール

最も簡単なインストール方法は、以下のワンライナーを実行することです：

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

または PyPI からインストールできます：

```bash
pip install kage-ai
```

`uv` を使ってインストールすることも可能です：

```bash
uv tool install git+https://github.com/igtm/kage.git
kage onboard
```

## セットアップ

1. **初期設定（初回のみ）**:
   ```bash
   kage onboard
   ```
   `~/.kage/` ディレクトリとデータベース、crontab のエントリーが作成されます。

2. **AIエンジンの設定**:
   `~/.kage/config.toml` を作成し、デフォルトで使用するモデルを指定します。
   ```toml
   default_ai_engine = "codex"
   ```

3. **プロジェクトの初期化**:
   タスクを実行したいプロジェクトのディレクトリで実行します。
   ```bash
   kage init
   ```
   `.kage/tasks/sample.toml` が作成されます。

## タスクの定義例

`.kage/tasks/` 内の `.toml` または `.md`（front matter）でタスクを定義できます。

- `*.toml`: 既存形式（1ファイルに複数タスクも可）
- `*.md`: front matter 形式、**1ファイル1タスク（promptタスクのみ）**

```toml
# AIを使った自動リファクタリング
[task_refactor]
name = "Daily Refactor"
cron = "0 3 * * *"
prompt = "src/ 内のコードを綺麗にしてください"
provider = "claude"

# JSON出力のパース例
[task_labels]
name = "Ticket Labeling"
cron = "*/30 * * * *"
prompt = "Issueを分類して JSON '{\"label\":\"...\"}' で返して: 'ログイン不可'"
provider = "codex_json"
parser_args = ".label"

# 標準のシェルコマンド
[task_cleanup]
name = "Log Cleanup"
cron = "0 0 * * 0"
command = "rm -rf ./logs/*.log"
shell = "bash"
```

```md
---
name: Nightly Research
cron: "0 2 * * *"
prompt: "候補ライブラリを比較し、差分を要約して"
provider: codex
---

# markdownは1ファイル1タスク（promptのみ）
```

## コマンド一覧

- `kage onboard`: グローバル設定とOSレベルのデーモン初期化。
- `kage init`: カレントディレクトリを kage プロジェクトとして初期化。
- `kage daemon install`: OSのスケジューラ（cron/launchd）への登録。
- `kage daemon remove`: OSのスケジューラからの登録解除。
- `kage daemon status`: デーモンの登録状態を確認。
- `kage config <key> <value> [--global]`: CLIから設定を更新。
- `kage doctor`: セットアップ状態と設定の健全性を診断。
- `kage ui`: Webダッシュボードの起動（デフォルト: [http://localhost:8484](http://localhost:8484)）。
- `kage logs`: ターミナルで実行履歴を表示。
- `kage run`: スケジュールされたタスクを即時一括実行（通常は cron/launchd から呼ばれます）。
- `kage task list`: すべての登録タスク一覧を表示。
- `kage task show <name>`: 指定タスクの詳細を表示。
- `kage task run <name>`: 指定タスクを即時実行。
- `kage project list`: 登録済みプロジェクト一覧を表示。
- `kage project remove [path]`: プロジェクト登録を解除。

## リリース / 公開

```bash
# 1) パッケージをビルド
uv build

# 2) GitHub Release を作成（例: v0.0.1）
gh release create v0.0.1 --title "kage v0.0.1" --generate-notes

# 3) PyPI に公開（トークン認証）
TWINE_USERNAME=__token__ \
TWINE_PASSWORD='<pypi-token>' \
uvx twine upload dist/*
```

## ライセンス

MIT
