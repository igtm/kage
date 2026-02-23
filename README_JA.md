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

または、`uv` を使って手動でインストールすることも可能です：

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

`.kage/tasks/` 内の `.toml` ファイルにタスクを記述します。

```toml
# AIを使った自動リファクタリング
[task.refactor]
name = "Daily Refactor"
cron = "0 3 * * *"
prompt = "src/ 内のコードを綺麗にしてください"
provider = "claude"

# JSON出力のパース例
[task.labels]
name = "Ticket Labeling"
cron = "*/30 * * * *"
prompt = "Issueを分類して JSON '{\"label\":\"...\"}' で返して: 'ログイン不可'"
provider = "codex_json"
parser_args = ".label"

# 標準のシェルコマンド
[task.cleanup]
name = "Log Cleanup"
cron = "0 0 * * 0"
command = "rm -rf ./logs/*.log"
shell = "bash"
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

## ライセンス

MIT
