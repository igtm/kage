# easy-worktree フック

このディレクトリには、easy-worktree (wt コマンド) のフックスクリプトが格納されています。

## wt コマンドとは

`wt` は Git worktree を簡単に管理するための CLI ツールです。複数のブランチで同時に作業する際に、ブランチごとに独立したディレクトリ（worktree）を作成・管理できます。

### 基本的な使い方

```bash
# リポジトリをクローン
wt clone <repository_url>

# 新しい worktree を作成（新規ブランチ）
wt add <作業名>

# セットアップ（フック実行など）をスキップして作成
wt add <作業名> --skip-setup

# 既存ブランチから worktree を作成
wt add <作業名> <既存ブランチ名>

# worktree 一覧を表示
wt list

# worktree を削除
wt rm <作業名>
```

詳細は https://github.com/igtm/easy-worktree を参照してください。

## 設定 (config.toml)

`.wt/config.toml` で以下の設定が可能です。

```toml
worktrees_dir = ".worktrees"   # worktree を作成するディレクトリ名
setup_files = [".env"]          # 自動セットアップでコピーするファイル一覧
setup_source_dir = ""           # 空なら自動判定。指定時はこのディレクトリからコピー
```

### ローカル設定 (config.local.toml)

`config.local.toml` を作成すると、設定をローカルでのみ上書きできます。このファイルは自動的に `.gitignore` に追加され、リポジトリにはコミットされません。

## post-add フック

`post-add` フックは、worktree 作成後に自動実行されるスクリプトです。

### 使用例

- 依存関係のインストール（npm install, pip install など）
- 設定ファイルのコピー（.env ファイルなど）
- ディレクトリの初期化
- VSCode ワークスペースの作成

### 利用可能な環境変数

- `WT_WORKTREE_PATH`: 作成された worktree のパス
- `WT_WORKTREE_NAME`: worktree の名前
- `WT_BASE_DIR`: メインリポジトリディレクトリのパス
- `WT_BRANCH`: ブランチ名
- `WT_ACTION`: アクション名（常に "add"）

### post-add.local について

`post-add.local` は、個人用のローカルフックです。このファイルは `.gitignore` に含まれているため、リポジトリにコミットされません。チーム全体で共有したいフックは `post-add` に、個人的な設定は `post-add.local` に記述してください。

`post-add` が存在する場合のみ、`post-add.local` も自動的に実行されます。
