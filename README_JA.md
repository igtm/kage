# kage 影 - 自律型 AI プロジェクトエージェント

![kage hero](./hero.png)

[English](./README.md) | 日本語

`kage` は、OS標準の **cron** や **launchd** を活用した、極めて軽量かつ透明性の高い AI エージェント実行レイヤーです。公式 AI CLI（`antigravity`, `gemini`, `claude`, `codex`, `opencode`, `copilot` 等）をヘッドレスモードで直接駆動し、常駐デーモンなしで動作します。仕事用のPCにインストールして開発リポジトリ内にやりたいことを Markdown で書き、あとはPCを起動したまま眠りにつくだけです。朝起きたときには AI があなたの代わりに仕事を終えており、答えの用意された状態で一日を始めることができます。

> **寝ている間に、成果を。** — `kage` はあなたの代わりに夜通しAIエージェントを走らせます。朝起きたとき、そこにあるのは「疑問」ではなく「答え」です。

## 設計思想 (Design Philosophy)

`kage` は、**「薄く、透明で、リソース効率の良い」** 実行レイヤーであることを目指して設計されています。

- **OS ネイティブ**: 独自の常駐デーモンを持ちません。**cron (Linux)** や **launchd (macOS)** という OS 標準の仕組みを利用して、必要な時だけ起動し、仕事を終えると速やかに終了します。待機時のメモリ消費はゼロです。
- **公式 CLI 活用**: Antigravity や Gemini、Claude、GCP SDK などの **公式 AI CLI ツール** をヘッドレスモードでそのまま利用します。非公式 API や不安定な内部実装に依存せず、確実な動作を提供します。
- **ステートレス & 透明性**: すべての実行はログに記録され、状態管理は SQLite と Markdown ファイルのみで行われるシンプルで追いかけやすい構成です。

## ダッシュボード

| 実行ログ | 設定 & タスク |
|:-:|:-:|
| ![実行ログ](./docs/execution-logs.png) | ![設定 & タスク](./docs/settings-n-tasks.png) |

## 特徴

- **自律型エージェントロジック**: タスクを GFM チェックリストへ自動分解し、進捗を追跡。
- **永続メモリシステム**: `.kage/memory/` に状態を保存し、実行を跨いだ文脈の維持が可能。
- **超軽量な実行**: OS 標準のスケジューラーを活用。バックグラウンドでの無駄なリソース消費がありません。
- **柔軟な実行形式**: AIプロンプト、シェルコマンド、カスタムスクリプトに対応。AI プロンプト（Markdown 本文）と直接コマンド実行（Front Matter 内の `command`）の両方をサポート。
- **コンパイル済みタスク**: `kage compile <task>` で prompt task から同名の `.lock.sh` を生成でき、保存された `prompt_hash` が現在の prompt 本文と一致している間だけその lock script が優先実行されます。
- **高度な制御 (Workflow)**:
    - **実行モード**: `continuous` (常時), `once` (一回), `autostop` (AIが完了判断時に停止)。
    - **多重起動制御**: `allow`, `forbid` (重複スキップ), `replace` (古い方を終了)。
    - **時間枠制限**: `allowed_hours: "9-17"`, `denied_hours: "12"` のように実行時間を制限。
- **Markdown 本位**: YAML front matter を持つシンプルな Markdown ファイルでタスクを定義。
- **コネクター**: Discord/Slack/Telegram との連携。タスク通知は常に有効。双方向チャットは `poll = true`（1分間隔のポーリング）または Discord の `realtime = true`（WebSocket で即時返信＋入力中表示）で有効化（⚠️ チャンネルの参加者にPC上のAIへのアクセスを許可します）。
- **思考プロセスの隔離**: AIエージェントの推論過程を `<think>` タグで隔離し、通知・summary・整形済み出力では除外します。`kage logs` では調査用に raw stream をそのまま確認できます。
- **多層的な設定**: `.kage/config.local.toml` > `.kage/config.toml` > `~/.kage/config.toml` > デフォルト。
- **Webダッシュボード**: 実行履歴、タスク管理、AIチャットを一箇所で提供。

connector を使う run では workspace 内の staging directory として `KAGE_ARTIFACT_DIR`（例: `.kage/tmp/connector-artifacts/<run_id>`）が作られます。受信した connector 添付は同じ run の `KAGE_ARTIFACT_DIR/incoming` に保存され、その場所が prompt に追記されるので provider 側が必要に応じて読む前提です。Discord / Slack / Telegram は `KAGE_ARTIFACT_DIR` 直下に最後に残っている top-level file を本文と一緒にすべて upload するので、そこには PNG / PDF など意図した最終成果物だけを残し、不要な Markdown / Marp / HTML、ダウンロード画像、中間 asset は終了前に削除してください。

デフォルト同梱の AI provider は `codex`, `claude`, `gemini`, `antigravity`, `opencode`, `copilot`, `aider` です。

Antigravity CLI を使う場合は `provider: antigravity` を指定します。built-in の command template は公式の `agy` binary を優先し、PATH 上で `antigravity` という実行名しか見えていない環境では自動でそちらへフォールバックします。connector chat 返信では、kage は最終回答だけを返すための簡潔な prompt を使い、Antigravity の model 引数を `--print` より前に置くことで、ユーザーのメッセージが CLI session metadata ではなく prompt として処理されるようにします。

詳細な技術解説は [技術構成ドキュメント](ARCHITECTURE_JA.md) を参照してください。

## インストール

```bash
curl -sSL https://raw.githubusercontent.com/igtm/kage/main/install.sh | bash
```

installer は `kage` 更新後に pending な install-time migration も自動実行します。

このリポジトリの skill は次のコマンドでも追加できます：
```bash
npx skills add https://github.com/igtm/kage
```

## クイックスタート

```bash
cd your-project
kage init         # 現在のディレクトリに kage を初期化
# .kage/tasks/*.md を編集してタスクを定義
kage ui           # Webダッシュボードを開く
```

## シェル補完 (Completion)

`kage` は Typer 標準の補完機能に対応しています。

```bash
# 推奨: シェルを明示してインストール
kage completion install bash
kage completion install zsh
```

スクリプトを確認・手動適用する場合:

```bash
# bash
kage completion show bash > ~/.kage-complete.bash
echo 'source ~/.kage-complete.bash' >> ~/.bashrc

# zsh
kage completion show zsh > ~/.kage-complete.zsh
echo 'source ~/.kage-complete.zsh' >> ~/.zshrc
```

現在のシェル自動判定で入れる場合は以下も使えます。

```bash
kage --install-completion
```

設定後はシェルを再読み込みしてください（`exec $SHELL -l`）。

シェル補完では `kage run <task>`、`kage compile <task>`、`kage logs [<task>]`、`kage task run <name>`、`kage task suspend <name>`、`kage task resume <name>`、`kage runs show <exec_id>` のような位置引数に対して task 名や最近の run id も候補に出ます。
`kage doctor` でも bash / zsh の completion script が入っているか確認できます。

## ユースケース

### 🌙 夜間技術選定（OCR モデルベンチマーク）

最強のユースケース: **寝る前にセットして、朝起きたら技術選定が完了している。**

1つのタスクが、cron実行ごとに未テストのOCRモデルを1つずつ実装、テストPDFに対して実行し、精度を記録。朝にはランキングレポートが完成しています。

`.kage/tasks/ocr_benchmark.md`:
```markdown
---
name: OCR Model Benchmark
cron: "0 * * * *"
provider: claude
mode: autostop
denied_hours: "9-23"
working_dir: ../../benchmark
---

# タスク: PDF OCR 技術評価

日本語の金融PDF文書からテキスト抽出するための、無料/OSSのOCRソリューションを体系的に評価します。

## 対象モデル（1実行につき1つテスト）
- Tesseract (jpn + jpn_vert)
- EasyOCR
- PaddleOCR
- Surya OCR
- DocTR (doctr)
- manga-ocr（縦書き対応）
- Google Vision API (無料枠)

## 手順
1. `.kage/memory/` を確認し、テスト済みモデルを特定する。
2. 上記リストから次の未テストモデルを選択する。
3. インストールし、`benchmark/test_{model_name}.py` にテストスクリプトを作成する。
4. `benchmark/test_pdfs/` のPDFファイルに対して実行する。
5. 測定: 文字精度 (CER)、処理時間、メモリ使用量。
6. 結果を `benchmark/results/{model_name}.json` に保存する。
7. `benchmark/RANKING.md` に全テスト済みモデルの比較表を更新する。
8. 全モデルのテストが完了したら、メモリにステータス "Completed" を設定する。
```

`working_dir` は任意です。絶対パスはそのまま使われ、相対パスは task file が置かれているディレクトリ（`.kage/tasks/`）基準で解決されます。

task を無効化せず一時停止する場合は、suspension metadata か CLI を使います。

```yaml
suspended_until: "2026-05-09T18:30:00+09:00"
suspended_reason: "2週間の休暇"
```

`kage task suspend <name> --for 2w --reason "Vacation"` はこれらの field を task file の front matter に書き込みます。`--for` は `m`, `h`, `d`, `w` のいずれか 1 token、`--until` は ISO date / datetime を受け付けます。日付だけを指定した場合は task timezone の午前 0 時に再開します。停止中の task は cron と手動 `kage run` のどちらでも skip され、意図的に 1 回だけ実行する場合は `kage run <task> --force` または `kage task run <task> --force` を使います。

朝起きた時:
```
benchmark/
├── RANKING.md              ← 比較表完成、意思決定可能
├── results/
│   ├── tesseract.json
│   ├── easyocr.json
│   ├── paddleocr.json
│   └── ...
└── test_pdfs/
    ├── invoice_001.pdf
    └── report_002.pdf
```

### 🔍 夜間コードベース監査

`.kage/tasks/audit.md`:
```markdown
---
name: Architecture Auditor
cron: "0 2 * * *"
provider: gemini
mode: continuous
denied_hours: "9-18"
---

# タスク: 夜間アーキテクチャ健全性チェック
コードベースを分析:
- デッドコードと未使用エクスポート
- 循環依存
- テスト未カバーのAPIエンドポイント
- セキュリティアンチパターン（ハードコードされたシークレット、SQLインジェクションリスク）

結果を `reports/audit_{date}.md` に出力。
```

### 🧪 夜間 PoC ビルダー

`.kage/tasks/poc_builder.md`:
```markdown
---
name: PoC Builder
cron: "30 0 * * *"
provider: claude
mode: autostop
denied_hours: "8-23"
---

# タスク: PoC（概念実証）の構築

`specs/next_poc.md` の仕様を読み、動作するプロトタイプを実装する。
- `poc/` ディレクトリに実装を作成
- セットアップ手順とデモコマンドを含む README を作成
- コア機能を検証する基本テストを作成
- PoCが機能したらステータスを "Completed" に設定
```

### ⚡ シンプルな例

**AI タスク** — 毎時ヘルスチェック:
```markdown
---
name: プロジェクト監査役
cron: "0 * * * *"
provider: gemini
---
現在のコードベースを分析し、アーキテクチャの乖離を確認してください。
```

同じ task を Antigravity CLI で動かす場合:

```markdown
---
name: プロジェクト監査役
cron: "0 * * * *"
provider: antigravity
---
現在のコードベースを分析し、アーキテクチャの乖離を確認してください。
```

**シェルコマンド・タスク** — 毎晩ログ削除:
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

| コマンド | 説明 |
|---------|-------------|
| `kage quest new <name> --direction "..."` | event駆動のquestを作成。ロールエージェント(scout→poc→strategist)がマインドマップ状のグラフを形成し、cron tickごとに1ノードをディスパッチ。`--max-agent-runs` で暴走防止予算を設定 |
| `kage quest list` | quest一覧とノード/実行回数の進捗 |
| `kage quest show <id>` | questのノード・エッジを表示 |
| `kage quest stop <id>` / `kage quest resume <id>` | questの一時停止/再開 |
| `kage quest abort-node <node_id>` | 単一ノードを強制abort |
| `kage onboard` | グローバルセットアップ |
| `kage init` | 現在のディレクトリに kage を初期化 |
| `kage run <task>` | 特定 task を即時実行。停止中 task は `--force` で実行 |
| `kage compile <task>` | prompt task から同名の `.lock.sh` override を生成 |
| `kage runs` | 相対日時付きの色付きテーブルで実行履歴を表示 |
| `kage runs show <exec_id>` | 実行メタデータ、状態、ログパスを表示 |
| `kage runs stop <exec_id>` | 実行中の run を停止 |
| `kage logs [<task>]` | task の最新 run の生ログ、または未指定時は全 task の結合ログを開く |
| `kage logs --run <exec_id>` | 特定 run の生ログを開く |
| `kage cron run` | scheduler ループを 1 回実行（cron / launchd 用） |
| `kage cron install` | システムスケジューラーに登録 |
| `kage cron status` | バックグラウンド実行状態の確認 |
| `kage task list` | 状態、実効 Type、Provider/Command 付きでタスク一覧を表示 |
| `kage task show <name>` | 詳細設定、停止状態、prompt hash を表示 |
| `kage task suspend <name> --for 2w` | `active` を変えずに future starts を一時停止 |
| `kage task resume <name>` | task を即時実行せず suspension metadata だけ削除 |
| `kage connector list` | 設定済みのコネクター一覧を表示 |
| `kage connector setup <type>` | コネクター（discord, slack, telegram）のセットアップガイドを表示 |
| `kage connector poll` | `poll = true` のコネクターを即座にポーリング |
| `kage connector realtime start [name]` | デタッチされたリアルタイムリスナーを開始 |
| `kage connector realtime stop [name]` | リアルタイムリスナーを停止 |
| `kage connector realtime restart [name]` | リアルタイムリスナーを再起動 |
| `kage connector realtime status` | 実行中のリアルタイムリスナーを表示 |
| `kage connector realtime run [name]` | リアルタイムリスナーを foreground で実行 |
| `kage migrate install` | pending な install-time migration を手動実行 |
| `kage doctor` | 設定と環境の診断 |
| `kage skill` | エージェントの指針を表示 |
| `kage ui` | Webダッシュボードを開く |
| `kage tui` | runs/tasks/connectors/config の4タブを持つ端末ダッシュボードを開く |

## Connectors

コネクターは Discord / Slack / Telegram といった外部チャットサービスと連携します。`notify_connectors` によるタスク通知は、認証情報さえ設定されていれば **常に有効** です。

双方向チャットを有効にする場合、各コネクターで **どちらか一方だけ** を選んでください。

- `poll = true` — cron/launchd 経由で 1 分ごとにメッセージを取得します。
- `realtime = true` — Discord のみ。Gateway WebSocket で即時受信し、入力中表示の上で即座に返信します。

すでに crontab に `kage cron run` が登録されている場合、リアルタイムリスナーは自動的に管理されます。`realtime = true` に設定してから最大 1 分で起動し、`realtime = true` を外すと次の cron 実行時に停止します。手動で管理する場合は以下のコマンドを使います。

```bash
kage connector realtime start [name]   # デタッチで開始
kage connector realtime stop [name]    # 停止
kage connector realtime restart [name] # 再起動
kage connector realtime status         # 実行中一覧
kage connector realtime run [name]     # foreground 実行（デバッグ用）
```

リアルタイムログは `~/.kage/logs/connector-realtime-<name>.log` に書き込まれ、起動時にローテーションされます。古いローテート済みログは 7 日以上経過するか 5 ファイルを超えたものから削除されます。

> **⚠️ セキュリティ警告**: `poll = true` または `realtime = true` を有効にすると、チャンネルの参加者が PC 上の AI と対話できるようになります。必ず一方だけを有効にし、プライベート/信頼できるチャンネルでのみ使用してください。

## Agents と マルチテナント分離

**Agent** はプロジェクト・コネクター・memory・system_prompt を所有するトップ概念です。組込みの agent `kage` は常に存在し削除できません。明示的な `agent` が無い connector / project は `kage` にフォールバックします。独自 agent を定義すれば、connnector に別人格を与え、コンテキストが漏れないようにできます。例えばプライベート Discord を agent `private` に、公開 Discord を agent `public` に bind すれば、会話が cross-over することはありません。

```toml
[agents.public]
system_prompt = """
あなたは公開用アシスタントです。簡潔丁寧に答えてください。
プライベートプロジェクトや他 agent の内容には言及しないでください。
"""
default_working_dir = "~/projects/public"

[agents.private]
system_prompt = "ユーザーのプライベートアシスタント。簡潔に。"
default_working_dir = "~/projects/private"

[connectors.discord_public]
type = "discord"
poll = true
bot_token = "..."
channel_id = "..."
agent = "public"          # この connector を public agent に bind

[connectors.discord_private]
type = "discord"
poll = true
bot_token = "..."
channel_id = "..."
agent = "private"
```

kage が AI provider を spawn する際、以下の環境変数を注入します。

- `KAGE_RUN_ID` — 権威となる実行 ID。CLI は SQLite の `executions.agent_name` から自分がどの agent かを判断します。この列は SQLite trigger で UPDATE/DELETE 不可能です。
- `KAGE_AGENT_NAME` — 表示用ヒントのみ。偽装しても無効で、常に DB が優先されます。

spawn されたシェル内で `kage *` コマンドを実行すると、その agent に紐づく connector / task / memory しか操作できません。他 agent のリソースには触れません。一方で、`KAGE_RUN_ID` が未設定の人間のシェルはスーパーユーザー扱いとなり scope の filter を bypass します（残留していると `kage doctor` で警告されます）。

### Agent Memory

各 agent は `~/.kage/agents/<agent_name>/memory/<slug>.md` に topic 単位の memory 空間を持ちます。実行開始時に kage は `<available_memories>` ブロックで memory の一覧を system prompt に注入します（`<name>` / `<description>` / `<updated_at>` のみで file path は隠蔽）。AI は本文が必要な時に CLI で取り出します。

```bash
kage memory list                              # 現 agent の memory 一覧
kage memory show <slug>                       # 本文を表示
kage memory write <slug> --description "..."  # 作成・上書き（本文は stdin から）
kage memory delete <slug>                      # 削除
kage memory search <query>                     # 本文の部分一致検索
```

memory は task ごとではなく agent 単位、上書き式（最新 state のみ保持、`updated_at` を更新）、agent 実行中は `kage memory` 自体も自 agent 配下に scope されます。かつての task memory（`.kage/memory/<task>/YYYY-MM-DD.json` や `task.json`）は廃止され、install migration が旧 `system_prompt.md` を backup 差替え、旧 memory dir を退避します。

### macOS launchd 独自設定
macOS では `cron` の代わりに `launchd` が使用されます。`config.toml` で以下の独自設定が可能です：

- `darwin_launchd_interval_seconds`: 起動間隔を秒単位で指定（最小 `15`）。
- `darwin_launchd_keep_alive`: `true` に設定すると、プロセスを常駐させます。

`kage runs` は実行履歴ビューです。デフォルトでは `4時間前` のような相対日時付きテーブルで表示し、`--absolute-time` を付けると従来どおり詳細なローカル日時を表示します。`kage logs` は run ごとの raw output viewer で、生ログ本体は `stdout.log`, `stderr.log`, `events.jsonl` として保持されます。`kage logs <task>` は 1 task の最新 run を開き、引数なしの `kage logs` は全 task のログを時系列順に結合して表示します。追従表示は `--follow` または `-f` が使えます。

prompt task と同名の compiled lock 例えば `.kage/tasks/nightly.lock.sh` が存在する場合、kage はその lock に保持された `prompt_hash` が現在の prompt 本文と一致している間だけ Markdown 本文の代わりにそれを実行します。prompt 本文を更新したら lock は stale 扱いになるので、`kage compile <task>` を再実行してください。`kage doctor`、`kage task list`、UI の task card でも fresh / stale / missing を確認できます。`kage task show <name>` では現在の prompt hash も確認できます。

`kage task list` では project 列は末尾ディレクトリ名だけを表示し、prompt task は `Prompt` または `Prompt (Compiled)` として見えます。provider 未指定でも `gemini (Inherited)` のように実際に使われる provider を表示します。built-in の `codex` 実行テンプレートは既定で `codex exec --yolo ...` を使います。

suspension は `active` とは別の状態です。`active: false` は task を無効化し、`suspended_until` は deadline まで新規実行だけを止めます。不正な `suspended_until` は fail closed として扱われるため、値を直すか `kage task resume <name>` するまで task は skip されます。

connector の `poll` 返信も同じ run 履歴に保存されます。`kage runs --source connector_poll` で絞り込み、`kage logs --run <exec_id>` で AI CLI の raw output を確認できます。

install-time migration は `src/kage/migrations/install/` 配下の module を自動検知して実行します。今後 migration を追加した場合も、`kage migrate install` と `install.sh` から同じルールで処理されます。

`kage tui` は Textual ベースの端末ダッシュボードです。ログ、タスク、Connector、設定の4タブを持ち、ログタブでは左の task/run 選択で右のログ表示を絞り込めます。タスクタブでは task 詳細、Connector タブではメッセージ履歴、設定タブでは global config を確認できます。

## 設定ファイル

| ファイル | スコープ |
|------|-------|
| `~/.kage/config.toml` | グローバル設定 (`default_ai_engine`, `working_dir`, `ui_port`, `ui_host` 等) |
| `.kage/config.toml` | プロジェクト共有設定 |
| `.kage/config.local.toml` | ローカル上書き設定 (git-ignored) |
| `.kage/system_prompt.md` | プロジェクト固有の AI 指針 |

provider ごとの model も同じ階層で上書きできます。単一の `model` に加えて、フォールバック用に `models` 配列も設定できます。

```toml
[providers.codex]
model = "gpt-5-codex"

[providers.claude]
models = ["claude-sonnet-4-5", "claude-haiku-4-5"]

[providers.antigravity]
model = "Gemini 3.5 Flash"

[providers.opencode]
models = ["openai/gpt-5-codex", "openai/gpt-5-mini"]
```

`models` を設定すると、kage は先頭から順にモデルを試行し、レート制限や使用制限に当たった場合だけ次のモデルへフォールバックします。すべてのモデルが失敗した場合は、その run は失敗になります。

built-in provider は既定で `--model` を使います。CLI から nested key を保存することもできます。

```bash
kage config default_ai_engine antigravity --global
kage config providers.antigravity.model "Gemini 3.5 Flash" --global
kage config providers.codex.model gpt-5-codex --global
kage config providers.claude.models '["claude-sonnet-4-5","claude-haiku-4-5"]' --global
kage config providers.codex.model gpt-5-mini --local
```

## ライセンス

MIT
